"""
SNDOIF -- complete end-to-end pipeline.

Runs the Ownership & Compliance Layer and Infrastructure Correlation
Layer, then fuses their evidence into a single confidence-scored
report of potential hidden relationships between the sample entities.
This is the project's actual deliverable: a due-diligence tool that
corroborates ownership evidence with independent technical evidence
before flagging a relationship for analyst review.
"""

import logging

from fusion.scoring import ENTITY_DOMAIN_MAP, score_all_pairs
from infrastructure.analytics_fingerprint import compare_fingerprints, fingerprint_site
from infrastructure.cert_transparency import compare_certificates
from infrastructure.hosting_correlation import cluster_by_shared_ip, cluster_by_subnet
from infrastructure.whois_lookup import batch_lookup, compare_domains
from ownership.companies_house import build_ownership_records
from ownership.ownership_graph import (
    build_graph,
    detect_jurisdiction_red_flags,
    detect_red_flags,
    entity_pairs_with_shared_person,
)
from ownership.sanctions_check import screen_beneficial_owners

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

COMPANY_SAMPLE = [
    "09446231",  # Monzo Bank Limited
    "08804411",  # Revolut Ltd
    "00000006",  # Marine and General Mutual Life Assurance Society (dissolved, old)
    "13211214",  # Wise Plc
    "07209813",  # Wise Payments Limited
    "11465966",  # Deliveroo International Ltd
    "10970586",  # Deliveroo SP Ltd
]


def _unique_pairs(items: list) -> list[tuple]:
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            pairs.append((items[i], items[j]))
    return pairs


def run_ownership_layer() -> tuple[list[str], list[dict]]:
    """Run the ownership pipeline and return (company names, shared-person pairs)."""
    logger.info("=== OWNERSHIP & COMPLIANCE LAYER ===")
    records = build_ownership_records(COMPANY_SAMPLE)

    all_names = []
    for record in records:
        all_names.extend(o["name"] for o in record.officers)
        all_names.extend(p["name"] for p in record.psc if p.get("name"))

    sanctions_matches = screen_beneficial_owners(all_names)
    graph = build_graph(records)
    red_flags = detect_red_flags(graph)
    jurisdiction_flags = detect_jurisdiction_red_flags(records)
    ownership_pairs = entity_pairs_with_shared_person(graph)

    print(f"Companies: {len(records)} | Sanctions matches: {len(sanctions_matches)} | "
          f"Shared directors: {len(red_flags['shared_directors'])} | "
          f"Circular ownership: {len(red_flags['circular_ownership'])} | "
          f"Jurisdiction flags: {len(jurisdiction_flags)}")

    company_names = [r.company_name for r in records]
    return company_names, ownership_pairs


def run_infrastructure_layer() -> list[dict]:
    """Run the infrastructure pipeline and return a combined overlap list."""
    logger.info("=== INFRASTRUCTURE CORRELATION LAYER ===")
    domains = list(set(ENTITY_DOMAIN_MAP.values()))

    overlaps = []

    whois_records = batch_lookup(domains)
    for record_a, record_b in _unique_pairs(whois_records):
        comparison = compare_domains(record_a, record_b)
        if comparison["same_registrar"] or comparison["same_registrant_org"] or comparison["shared_name_servers"]:
            overlaps.append(comparison)

    shared_ips = cluster_by_shared_ip(domains)
    for ip, doms in shared_ips.items():
        for domain_a, domain_b in _unique_pairs(doms):
            overlaps.append({"domain_a": domain_a, "domain_b": domain_b, "shared_ip": ip})

    for domain_a, domain_b in _unique_pairs(domains):
        comparison = compare_certificates(domain_a, domain_b)
        if comparison["shared_certificate_found"]:
            overlaps.append({"domain_a": domain_a, "domain_b": domain_b, "shared_cert": True})

    fingerprints = []
    for domain in domains:
        try:
            fingerprints.append(fingerprint_site(f"https://{domain}"))
        except Exception as error:
            logger.warning("Could not fingerprint %s: %s", domain, error)

    for fp_a, fp_b in _unique_pairs(fingerprints):
        comparison = compare_fingerprints(fp_a, fp_b)
        if comparison["shared_tracking_ids"] or comparison["same_favicon"]:
            overlaps.append({
                "domain_a": fp_a["url"].replace("https://", ""),
                "domain_b": fp_b["url"].replace("https://", ""),
            })

    print(f"Infrastructure overlaps found: {len(overlaps)}")
    return overlaps


def main() -> None:
    print("=" * 70)
    print("SNDOIF -- SHELL NETWORK DETECTION THROUGH OWNERSHIP-INFRASTRUCTURE FUSION")
    print("=" * 70)

    company_names, ownership_pairs = run_ownership_layer()
    infrastructure_overlaps = run_infrastructure_layer()

    logger.info("=== FUSION ===")
    scored_pairs = score_all_pairs(company_names, ownership_pairs, infrastructure_overlaps)

    print("\n" + "=" * 70)
    print("FINAL FUSED REPORT")
    print("=" * 70)

    high = [p for p in scored_pairs if p["confidence"] == "high"]
    low = [p for p in scored_pairs if p["confidence"] == "low"]

    print(f"\nHIGH confidence (both ownership + infrastructure evidence): {len(high)}")
    for pair in high:
        print(f"  - {pair['company_a']} <-> {pair['company_b']}")

    print(f"\nLOW confidence (single evidence type -- flagged for manual review): {len(low)}")
    for pair in low:
        evidence_type = "ownership" if pair["has_ownership_evidence"] else "infrastructure"
        print(f"  - {pair['company_a']} <-> {pair['company_b']} (only {evidence_type} evidence)")


if __name__ == "__main__":
    main()
