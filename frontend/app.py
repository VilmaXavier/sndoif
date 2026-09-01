"""
SNDOIF -- web frontend, both layers.

Two ways to use it:
1. Search a single company by name/number -- checked against the
   growing known-entities set for connections.
2. Directly compare two specific companies for shared directors,
   sanctions exposure, and infrastructure overlap.

Every successful single-company search permanently joins the known
entities store, so the tool's coverage grows over time.
"""

import logging
import os

import networkx as nx
from flask import Flask, render_template, request

from fusion.scoring import score_all_pairs
from fusion.visualization import build_visualization
from infrastructure.analytics_fingerprint import compare_fingerprints, fingerprint_site
from infrastructure.cert_transparency import compare_certificates
from infrastructure.hosting_correlation import cluster_by_shared_ip
from infrastructure.whois_lookup import batch_lookup, compare_domains
from ownership.companies_house import build_ownership_records, search_companies_by_name
from ownership.entity_store import add_known_company, load_known_companies
from ownership.ownership_graph import (
    build_graph,
    detect_jurisdiction_red_flags,
    detect_red_flags,
    entity_pairs_with_shared_person,
)
from ownership.sanctions_check import screen_beneficial_owners

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

KNOWN_DOMAINS = ["monzo.com", "revolut.com", "wise.com", "deliveroo.co.uk"]

GRAPH_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(GRAPH_OUTPUT_DIR, exist_ok=True)


@app.route("/", methods=["GET"])
def index():
    known_count = len(load_known_companies())
    return render_template("index.html", known_count=known_count)


@app.route("/compare", methods=["GET"])
def compare_form():
    return render_template("compare.html")


@app.route("/search-by-name", methods=["POST"])
def search_by_name():
    query = request.form.get("query", "").strip()
    if not query:
        return render_template("index.html", error="Please enter a company name.", known_count=len(load_known_companies()))

    logger.info("Searching by name: %s", query)
    results = search_companies_by_name(query)
    return render_template("name_results.html", query=query, results=results)


def _run_infrastructure_checks_pair(domain_a: str, domain_b: str) -> tuple[list[str], bool]:
    """Best-effort infrastructure comparison between exactly two domains."""
    overlaps = []
    fully_succeeded = True

    try:
        records = batch_lookup([domain_a, domain_b])
        if len(records) == 2:
            comparison = compare_domains(records[0], records[1])
            if comparison["same_registrar"]:
                overlaps.append(f"Same registrar: {records[0]['registrar']}")
            if comparison["same_registrant_org"]:
                overlaps.append(f"Same registrant organization: {records[0]['registrant_org']}")
            if comparison["shared_name_servers"]:
                overlaps.append(f"Shared name servers: {', '.join(comparison['shared_name_servers'])}")
    except Exception as error:
        logger.warning("WHOIS comparison failed: %s", error)
        fully_succeeded = False

    try:
        shared_ips = cluster_by_shared_ip([domain_a, domain_b])
        for ip in shared_ips:
            overlaps.append(f"Shared IP address: {ip}")
    except Exception as error:
        logger.warning("Hosting comparison failed: %s", error)
        fully_succeeded = False

    try:
        cert_comparison = compare_certificates(domain_a, domain_b)
        if cert_comparison["shared_certificate_found"]:
            overlaps.append(f"Shared SSL certificate covering: {', '.join(cert_comparison['shared_domains'])}")
    except Exception as error:
        logger.warning("Certificate comparison failed: %s", error)
        fully_succeeded = False

    try:
        fp_a = fingerprint_site(f"https://{domain_a}")
        fp_b = fingerprint_site(f"https://{domain_b}")
        fp_comparison = compare_fingerprints(fp_a, fp_b)
        for tracking_type, ids in fp_comparison["shared_tracking_ids"].items():
            overlaps.append(f"Shared {tracking_type}: {', '.join(ids)}")
        if fp_comparison["same_favicon"]:
            overlaps.append("Identical favicon image")
    except Exception as error:
        logger.warning("Analytics comparison failed: %s", error)
        fully_succeeded = False

    return overlaps, fully_succeeded


@app.route("/compare", methods=["POST"])
def compare():
    company_a_number = request.form.get("company_a", "").strip()
    company_b_number = request.form.get("company_b", "").strip()
    domain_a = request.form.get("domain_a", "").strip()
    domain_b = request.form.get("domain_b", "").strip()

    if not company_a_number or not company_b_number:
        return render_template("compare.html", error="Please enter both company numbers.")

    logger.info("Comparing %s vs %s", company_a_number, company_b_number)

    records = build_ownership_records([company_a_number, company_b_number])
    if len(records) < 2:
        return render_template("compare.html", error="Could not find one or both company numbers.")

    record_a, record_b = records[0], records[1]

    # Shared people: intersect the officer/PSC names of each company directly.
    names_a = {o["name"] for o in record_a.officers} | {p["name"] for p in record_a.psc if p.get("name")}
    names_b = {o["name"] for o in record_b.officers} | {p["name"] for p in record_b.psc if p.get("name")}
    shared_people = sorted(names_a & names_b)

    sanctions_matches = screen_beneficial_owners(list(names_a | names_b))

    infra_overlaps = []
    infra_note = None
    if domain_a and domain_b:
        infra_overlaps, fully_succeeded = _run_infrastructure_checks_pair(domain_a, domain_b)
        if not fully_succeeded:
            infra_note = "Some infrastructure checks failed (external service issue) -- results may be incomplete."
    else:
        infra_note = "No domains provided -- infrastructure checks skipped."

    has_ownership_evidence = len(shared_people) > 0
    has_infrastructure_evidence = len(infra_overlaps) > 0

    if has_ownership_evidence and has_infrastructure_evidence:
        confidence = "high"
    elif has_ownership_evidence or has_infrastructure_evidence:
        confidence = "low"
    else:
        confidence = "none"

    # Both compared companies also join the known-entities set, same
    # as single-company searches -- they were successfully verified
    # to exist, so future searches benefit from knowing about them too.
    add_known_company(company_a_number)
    add_known_company(company_b_number)

    return render_template(
        "compare_results.html",
        company_a_name=record_a.company_name,
        company_b_name=record_b.company_name,
        shared_people=shared_people,
        sanctions_matches=sanctions_matches,
        infra_overlaps=infra_overlaps,
        infra_note=infra_note,
        confidence=confidence,
    )


def _run_infrastructure_checks(searched_domain: str) -> tuple[list[dict], bool]:
    domains = list(dict.fromkeys([searched_domain] + KNOWN_DOMAINS))
    overlaps = []
    fully_succeeded = True

    try:
        whois_records = batch_lookup(domains)
        for i in range(len(whois_records)):
            for j in range(i + 1, len(whois_records)):
                comparison = compare_domains(whois_records[i], whois_records[j])
                if comparison["same_registrar"] or comparison["same_registrant_org"] or comparison["shared_name_servers"]:
                    overlaps.append(comparison)
    except Exception as error:
        logger.warning("WHOIS check failed: %s", error)
        fully_succeeded = False

    try:
        shared_ips = cluster_by_shared_ip(domains)
        for ip, doms in shared_ips.items():
            for i in range(len(doms)):
                for j in range(i + 1, len(doms)):
                    overlaps.append({"domain_a": doms[i], "domain_b": doms[j]})
    except Exception as error:
        logger.warning("Hosting check failed: %s", error)
        fully_succeeded = False

    for other_domain in KNOWN_DOMAINS:
        try:
            comparison = compare_certificates(searched_domain, other_domain)
            if comparison["shared_certificate_found"]:
                overlaps.append({"domain_a": searched_domain, "domain_b": other_domain})
        except Exception as error:
            logger.warning("Certificate check failed for %s vs %s: %s", searched_domain, other_domain, error)
            fully_succeeded = False
            break

    try:
        fingerprints = [fingerprint_site(f"https://{d}") for d in domains]
        for i in range(len(fingerprints)):
            for j in range(i + 1, len(fingerprints)):
                comparison = compare_fingerprints(fingerprints[i], fingerprints[j])
                if comparison["shared_tracking_ids"] or comparison["same_favicon"]:
                    overlaps.append({
                        "domain_a": fingerprints[i]["url"].replace("https://", ""),
                        "domain_b": fingerprints[j]["url"].replace("https://", ""),
                    })
    except Exception as error:
        logger.warning("Analytics fingerprint check failed: %s", error)
        fully_succeeded = False

    return overlaps, fully_succeeded


@app.route("/search", methods=["POST"])
def search():
    company_number = request.form.get("company_number", "").strip()
    searched_domain = request.form.get("domain", "").strip()

    if not company_number:
        return render_template("index.html", error="Please enter a company number.", known_count=len(load_known_companies()))

    logger.info("Searching company number: %s (domain: %s)", company_number, searched_domain or "none given")

    known_companies = load_known_companies()
    all_numbers = list(dict.fromkeys(known_companies + [company_number]))
    records = build_ownership_records(all_numbers)

    searched_record = next((r for r in records if r.company_number == company_number), None)
    if searched_record is None:
        return render_template("index.html", error=f"Could not find company number '{company_number}'.", known_count=len(known_companies))

    add_known_company(company_number)

    sanctions_matches = screen_beneficial_owners(
        [o["name"] for o in searched_record.officers]
        + [p["name"] for p in searched_record.psc if p.get("name")]
    )

    graph = build_graph(records)
    red_flags = detect_red_flags(graph)
    jurisdiction_flags = detect_jurisdiction_red_flags(records)
    ownership_pairs = entity_pairs_with_shared_person(graph)

    infrastructure_overlaps = []
    infra_note = "No domain provided -- infrastructure checks skipped."
    if searched_domain:
        logger.info("Running best-effort infrastructure checks for %s", searched_domain)
        infrastructure_overlaps, fully_succeeded = _run_infrastructure_checks(searched_domain)
        infra_note = (
            "Infrastructure checks completed." if fully_succeeded
            else "Infrastructure checks partially failed (external service issue) -- results may be incomplete."
        )

    company_names = [r.company_name for r in records]
    scored_pairs = score_all_pairs(company_names, ownership_pairs, infrastructure_overlaps)

    relevant_pairs = [p for p in scored_pairs if searched_record.company_name in (p["company_a"], p["company_b"])]
    relevant_shared_directors = [f for f in red_flags["shared_directors"] if searched_record.company_name in f["companies"]]

    if searched_record.company_name in graph:
        focused_graph = nx.ego_graph(graph, searched_record.company_name, radius=2, undirected=True)
    else:
        focused_graph = graph

    focused_filename = f"graph_focused_{company_number}.html"
    full_filename = f"graph_full_{company_number}.html"

    build_visualization(focused_graph, relevant_pairs, output_path=os.path.join(GRAPH_OUTPUT_DIR, focused_filename))
    build_visualization(graph, scored_pairs, output_path=os.path.join(GRAPH_OUTPUT_DIR, full_filename))

    return render_template(
        "results.html",
        company_name=searched_record.company_name,
        company_number=company_number,
        company_status=searched_record.company_status,
        officer_count=len(searched_record.officers),
        psc_count=len(searched_record.psc),
        sanctions_matches=sanctions_matches,
        shared_directors=relevant_shared_directors,
        jurisdiction_flags=[f for f in jurisdiction_flags if f["company_name"] == searched_record.company_name],
        scored_pairs=relevant_pairs,
        focused_filename=focused_filename,
        full_filename=full_filename,
        infra_note=infra_note,
        known_count=len(all_numbers),
    )


if __name__ == "__main__":
    app.run(debug=True)
