"""
SNDOIF -- web frontend, both layers.
"""

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import networkx as nx
from flask import Flask, jsonify, render_template, request, send_file

from fusion.scoring import score_all_pairs
from fusion.visualization import build_visualization
from infrastructure.analytics_fingerprint import compare_fingerprints, fingerprint_site
from infrastructure.cert_transparency import compare_certificates
from infrastructure.hosting_correlation import cluster_by_shared_ip
from infrastructure.whois_lookup import batch_lookup, compare_domains
from ownership.companies_house import build_ownership_records, search_companies_by_name
from ownership.domain_guesser import guess_domains
from ownership.entity_store import add_known_company, load_known_companies
from ownership.ownership_graph import (
    build_graph,
    detect_jurisdiction_red_flags,
    detect_red_flags,
    entity_pairs_with_shared_person,
)
from ownership.report_export import build_comparison_pdf, build_search_pdf
from ownership.sanctions_check import screen_beneficial_owners

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

KNOWN_DOMAINS = ["monzo.com", "revolut.com", "wise.com", "deliveroo.co.uk"]

GRAPH_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(GRAPH_OUTPUT_DIR, exist_ok=True)

COMPARISON_RESULTS = {}
SEARCH_RESULTS = {}


def _check_domain_belongs_to_company(domain, company_name):
    """Best-effort check: does this domain match one of the domains our
    own guesser would independently produce for this company name?
    There is no official public registry mapping a UK company number to
    its website domain, so this cannot be a guaranteed verification --
    only a sanity check. A False result means the domain could not be
    confirmed; it does NOT necessarily mean the domain is wrong.
    """
    guessed = [d.lower() for d in guess_domains(company_name)]
    return domain.lower().strip() in guessed


@app.route("/", methods=["GET"])
def index():
    known_count = len(load_known_companies())
    return render_template("index.html", known_count=known_count)


@app.route("/compare", methods=["GET"])
def compare_form():
    return render_template("compare.html")


@app.route("/guess-domain", methods=["POST"])
def guess_domain_endpoint():
    company_number = request.json.get("company_number", "").strip()
    if not company_number:
        return jsonify({"domains": []})

    records = build_ownership_records([company_number])
    if not records:
        return jsonify({"domains": []})

    domains = guess_domains(records[0].company_name)
    return jsonify({"domains": domains})


@app.route("/validate-domain", methods=["POST"])
def validate_domain_endpoint():
    """Real-time check used by the compare page's inline validation,
    called via JavaScript when the user leaves a domain field --
    the same pattern as inline password-rule validation.
    """
    company_number = request.json.get("company_number", "").strip()
    domain = request.json.get("domain", "").strip()

    if not company_number or not domain:
        return jsonify({"valid": True, "message": ""})

    records = build_ownership_records([company_number])
    if not records:
        return jsonify({"valid": True, "message": ""})

    company_name = records[0].company_name
    is_valid = _check_domain_belongs_to_company(domain, company_name)

    message = "" if is_valid else "This domain could not be confirmed as belonging to " + company_name + "."
    return jsonify({"valid": is_valid, "message": message})


@app.route("/search-by-name", methods=["POST"])
def search_by_name():
    query = request.form.get("query", "").strip()
    if not query:
        return render_template("index.html", error="Please enter a company name.", known_count=len(load_known_companies()))

    logger.info("Searching by name: %s", query)
    results = search_companies_by_name(query)
    return render_template("name_results.html", query=query, results=results)


def _whois_check_pair(domain_a, domain_b):
    findings = []
    records = batch_lookup([domain_a, domain_b])
    if len(records) == 2:
        comparison = compare_domains(records[0], records[1])
        if comparison["same_registrar"]:
            findings.append("Same registrar: " + str(records[0]["registrar"]))
        if comparison["same_registrant_org"]:
            findings.append("Same registrant organization: " + str(records[0]["registrant_org"]))
        if comparison["shared_name_servers"]:
            findings.append("Shared name servers: " + ", ".join(comparison["shared_name_servers"]))
    return findings


def _hosting_check_pair(domain_a, domain_b):
    findings = []
    shared_ips = cluster_by_shared_ip([domain_a, domain_b])
    for ip in shared_ips:
        findings.append("Shared IP address: " + ip)
    return findings


def _cert_check_pair(domain_a, domain_b):
    findings = []
    comparison = compare_certificates(domain_a, domain_b)
    if comparison["shared_certificate_found"]:
        findings.append("Shared SSL certificate covering: " + ", ".join(comparison["shared_domains"]))
    return findings


def _analytics_check_pair(domain_a, domain_b):
    findings = []
    fp_a = fingerprint_site("https://" + domain_a)
    fp_b = fingerprint_site("https://" + domain_b)
    comparison = compare_fingerprints(fp_a, fp_b)
    for tracking_type, ids in comparison["shared_tracking_ids"].items():
        findings.append("Shared " + tracking_type + ": " + ", ".join(ids))
    if comparison["same_favicon"]:
        findings.append("Identical favicon image")
    return findings


def _run_infrastructure_checks_pair(domain_a, domain_b):
    checks = {
        "whois": _whois_check_pair, "hosting": _hosting_check_pair,
        "certificates": _cert_check_pair, "analytics": _analytics_check_pair,
    }
    overlaps = []
    fully_succeeded = True
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_name = {}
        for name, func in checks.items():
            future_to_name[executor.submit(func, domain_a, domain_b)] = name
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                overlaps.extend(future.result())
            except Exception as error:
                logger.warning("%s check failed: %s", name, error)
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

    names_a = set(o["name"] for o in record_a.officers) | set(p["name"] for p in record_a.psc if p.get("name"))
    names_b = set(o["name"] for o in record_b.officers) | set(p["name"] for p in record_b.psc if p.get("name"))
    shared_people = sorted(names_a & names_b)

    sanctions_matches = screen_beneficial_owners(list(names_a | names_b))

    domain_warnings = []
    if domain_a and not _check_domain_belongs_to_company(domain_a, record_a.company_name):
        domain_warnings.append("'" + domain_a + "' could not be automatically confirmed as belonging to " + record_a.company_name + " -- treat any infrastructure findings involving it with caution.")
    if domain_b and not _check_domain_belongs_to_company(domain_b, record_b.company_name):
        domain_warnings.append("'" + domain_b + "' could not be automatically confirmed as belonging to " + record_b.company_name + " -- treat any infrastructure findings involving it with caution.")

    infra_overlaps = []
    infra_note = None
    if domain_a and domain_b:
        if domain_a.lower().strip() == domain_b.lower().strip():
            infra_note = "Both companies resolved to the same domain (" + domain_a + ") -- infrastructure checks skipped, since comparing a domain to itself would trivially match on everything. Verify the domains are correct for each specific company."
        else:
            infra_overlaps, fully_succeeded = _run_infrastructure_checks_pair(domain_a, domain_b)
            notes = []
            if not fully_succeeded:
                notes.append("Some infrastructure checks failed (external service issue) -- results may be incomplete.")
            notes.extend(domain_warnings)
            infra_note = " ".join(notes) if notes else None
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

    add_known_company(company_a_number)
    add_known_company(company_b_number)

    result_id = str(uuid.uuid4())
    COMPARISON_RESULTS[result_id] = {
        "company_a_name": record_a.company_name,
        "company_b_name": record_b.company_name,
        "confidence": confidence,
        "shared_people": shared_people,
        "sanctions_matches": sanctions_matches,
        "infra_overlaps": infra_overlaps,
        "infra_note": infra_note,
    }

    return render_template(
        "compare_results.html",
        company_a_name=record_a.company_name,
        company_b_name=record_b.company_name,
        shared_people=shared_people,
        sanctions_matches=sanctions_matches,
        infra_overlaps=infra_overlaps,
        infra_note=infra_note,
        confidence=confidence,
        result_id=result_id,
    )


@app.route("/compare/export/<result_id>", methods=["GET"])
def export_comparison_pdf(result_id):
    result = COMPARISON_RESULTS.get(result_id)
    if result is None:
        return "Report not found or expired -- please run the comparison again.", 404

    output_path = os.path.join(GRAPH_OUTPUT_DIR, "comparison_" + result_id + ".pdf")
    build_comparison_pdf(output_path, **result)

    return send_file(output_path, as_attachment=True, download_name="sndoif_comparison_report.pdf")


@app.route("/search/export/<result_id>", methods=["GET"])
def export_search_pdf(result_id):
    result = SEARCH_RESULTS.get(result_id)
    if result is None:
        return "Report not found or expired -- please run the search again.", 404

    output_path = os.path.join(GRAPH_OUTPUT_DIR, "search_" + result_id + ".pdf")
    build_search_pdf(output_path, **result)

    return send_file(output_path, as_attachment=True, download_name="sndoif_search_report.pdf")


def _run_infrastructure_checks(searched_domain):
    domains = list(dict.fromkeys([searched_domain] + KNOWN_DOMAINS))
    overlaps = []
    fully_succeeded = True

    def whois_and_hosting():
        results = []
        whois_records = batch_lookup(domains)
        for i in range(len(whois_records)):
            for j in range(i + 1, len(whois_records)):
                comparison = compare_domains(whois_records[i], whois_records[j])
                if comparison["same_registrar"] or comparison["same_registrant_org"] or comparison["shared_name_servers"]:
                    results.append(comparison)
        shared_ips = cluster_by_shared_ip(domains)
        for ip, doms in shared_ips.items():
            for i in range(len(doms)):
                for j in range(i + 1, len(doms)):
                    results.append({"domain_a": doms[i], "domain_b": doms[j]})
        return results

    def certificates():
        results = []
        for other_domain in KNOWN_DOMAINS:
            comparison = compare_certificates(searched_domain, other_domain)
            if comparison["shared_certificate_found"]:
                results.append({"domain_a": searched_domain, "domain_b": other_domain})
        return results

    def analytics():
        results = []
        fingerprints = [fingerprint_site("https://" + d) for d in domains]
        for i in range(len(fingerprints)):
            for j in range(i + 1, len(fingerprints)):
                comparison = compare_fingerprints(fingerprints[i], fingerprints[j])
                if comparison["shared_tracking_ids"] or comparison["same_favicon"]:
                    results.append({
                        "domain_a": fingerprints[i]["url"].replace("https://", ""),
                        "domain_b": fingerprints[j]["url"].replace("https://", ""),
                    })
        return results

    checks = {"whois_hosting": whois_and_hosting, "certificates": certificates, "analytics": analytics}
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_name = {}
        for name, func in checks.items():
            future_to_name[executor.submit(func)] = name
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                overlaps.extend(future.result())
            except Exception as error:
                logger.warning("%s check failed: %s", name, error)
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

    searched_record = None
    for r in records:
        if r.company_number == company_number:
            searched_record = r
            break

    if searched_record is None:
        return render_template("index.html", error="Could not find company number '" + company_number + "'.", known_count=len(known_companies))

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
        domain_warning = None
        if not _check_domain_belongs_to_company(searched_domain, searched_record.company_name):
            domain_warning = "'" + searched_domain + "' could not be automatically confirmed as belonging to " + searched_record.company_name + " -- treat infrastructure findings with caution."
        logger.info("Running best-effort infrastructure checks for %s", searched_domain)
        infrastructure_overlaps, fully_succeeded = _run_infrastructure_checks(searched_domain)
        notes = []
        if fully_succeeded:
            notes.append("Infrastructure checks completed.")
        else:
            notes.append("Infrastructure checks partially failed (external service issue) -- results may be incomplete.")
        if domain_warning:
            notes.append(domain_warning)
        infra_note = " ".join(notes)

    company_names = [r.company_name for r in records]
    scored_pairs = score_all_pairs(company_names, ownership_pairs, infrastructure_overlaps)

    relevant_pairs = [p for p in scored_pairs if searched_record.company_name in (p["company_a"], p["company_b"])]
    relevant_shared_directors = [f for f in red_flags["shared_directors"] if searched_record.company_name in f["companies"]]

    if searched_record.company_name in graph:
        focused_graph = nx.ego_graph(graph, searched_record.company_name, radius=2, undirected=True)
    else:
        focused_graph = graph

    focused_filename = "graph_focused_" + company_number + ".html"
    full_filename = "graph_full_" + company_number + ".html"

    build_visualization(focused_graph, relevant_pairs, output_path=os.path.join(GRAPH_OUTPUT_DIR, focused_filename))
    build_visualization(graph, scored_pairs, output_path=os.path.join(GRAPH_OUTPUT_DIR, full_filename))

    result_id = str(uuid.uuid4())
    SEARCH_RESULTS[result_id] = {
        "company_name": searched_record.company_name,
        "company_number": company_number,
        "company_status": searched_record.company_status,
        "officer_count": len(searched_record.officers),
        "psc_count": len(searched_record.psc),
        "sanctions_matches": sanctions_matches,
        "shared_directors": relevant_shared_directors,
        "jurisdiction_flags": [f for f in jurisdiction_flags if f["company_name"] == searched_record.company_name],
        "scored_pairs": relevant_pairs,
        "infra_note": infra_note,
    }

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
        result_id=result_id,
    )


if __name__ == "__main__":
    app.run(debug=True)
