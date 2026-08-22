"""
SNDOIF -- web frontend, both layers.

Search by company name or number. If a domain is provided, runs the
Infrastructure Correlation Layer alongside the Ownership & Compliance
Layer, with a reduced retry budget suited to a live web request --
external OSINT services (crt.sh especially) are frequently slow or
unavailable, and a single search should not hang indefinitely because
of them. Infrastructure evidence is best-effort: if it fails, the page
still renders with ownership-only results.
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

BASE_SAMPLE = [
    "09446231", "08804411", "00000006",
    "13211214", "07209813", "11465966", "10970586",
]

# Domains already known for the base sample, so infrastructure checks
# can run against them even when the newly searched company's own
# domain isn't known in advance.
KNOWN_DOMAINS = ["monzo.com", "revolut.com", "wise.com", "deliveroo.co.uk"]

GRAPH_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(GRAPH_OUTPUT_DIR, exist_ok=True)


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/search-by-name", methods=["POST"])
def search_by_name():
    query = request.form.get("query", "").strip()
    if not query:
        return render_template("index.html", error="Please enter a company name.")

    logger.info("Searching by name: %s", query)
    results = search_companies_by_name(query)
    return render_template("name_results.html", query=query, results=results)


def _run_infrastructure_checks(searched_domain: str) -> tuple[list[dict], bool]:
    """Best-effort infrastructure checks against the searched domain
    plus known sample domains. Returns (overlaps, succeeded_fully).

    Any individual check failing is logged and skipped -- this
    function is designed to always return SOMETHING usable rather
    than raising, since infrastructure evidence is a bonus signal for
    the web flow, not a required one.
    """
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

    # crt.sh: only check the searched domain against each known domain
    # (not every pair) and only ONE attempt each, to keep a single web
    # request from taking minutes when crt.sh is under load.
    for other_domain in KNOWN_DOMAINS:
        try:
            comparison = compare_certificates(searched_domain, other_domain)
            if comparison["shared_certificate_found"]:
                overlaps.append({"domain_a": searched_domain, "domain_b": other_domain})
        except Exception as error:
            logger.warning("Certificate check failed for %s vs %s: %s", searched_domain, other_domain, error)
            fully_succeeded = False
            break  # crt.sh being down affects every pair equally -- no point retrying each one

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
        return render_template("index.html", error="Please enter a company number.")

    logger.info("Searching company number: %s (domain: %s)", company_number, searched_domain or "none given")

    all_numbers = list(dict.fromkeys(BASE_SAMPLE + [company_number]))
    records = build_ownership_records(all_numbers)

    searched_record = next((r for r in records if r.company_number == company_number), None)
    if searched_record is None:
        return render_template(
            "index.html",
            error=f"Could not find company number '{company_number}'.",
        )

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

    relevant_pairs = [
        p for p in scored_pairs
        if searched_record.company_name in (p["company_a"], p["company_b"])
    ]
    relevant_shared_directors = [
        f for f in red_flags["shared_directors"]
        if searched_record.company_name in f["companies"]
    ]

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
    )


if __name__ == "__main__":
    app.run(debug=True)
