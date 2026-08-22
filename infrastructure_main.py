"""
End-to-end pipeline entry point for the Infrastructure Correlation Layer.

Runs all four infrastructure modules against a real domain sample and
reports a combined summary: WHOIS overlap, certificate transparency
overlap, hosting/subnet clustering, and analytics fingerprint overlap.
"""

import logging

from infrastructure.analytics_fingerprint import compare_fingerprints, fingerprint_site
from infrastructure.cert_transparency import compare_certificates
from infrastructure.hosting_correlation import cluster_by_shared_ip, cluster_by_subnet
from infrastructure.whois_lookup import batch_lookup, compare_domains

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Real domains matching companies already in the ownership layer's
# sample (main.py), so both layers are pointed at the same real-world
# subjects.
DOMAIN_SAMPLE = [
    "monzo.com",
    "revolut.com",
    "wise.com",
    "deliveroo.co.uk",
]


def _unique_pairs(items: list[str]) -> list[tuple[str, str]]:
    """Generate every unique pair from a list, same index-guard pattern
    used in ownership_graph.py's entity_pairs_with_shared_person().
    """
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            pairs.append((items[i], items[j]))
    return pairs


def main() -> None:
    """Run the full infrastructure correlation pipeline on the sample."""
    logger.info("Running infrastructure correlation on %d domains", len(DOMAIN_SAMPLE))

    print("\n" + "=" * 60)
    print("SNDOIF INFRASTRUCTURE CORRELATION LAYER -- PIPELINE SUMMARY")
    print("=" * 60)

    # --- WHOIS ---
    whois_records = batch_lookup(DOMAIN_SAMPLE)
    print(f"\nWHOIS fetched: {len(whois_records)} of {len(DOMAIN_SAMPLE)} domains")

    whois_overlaps = []
    for record_a, record_b in _unique_pairs(whois_records):
        comparison = compare_domains(record_a, record_b)
        if comparison["same_registrar"] or comparison["same_registrant_org"] or comparison["shared_name_servers"]:
            whois_overlaps.append(comparison)

    print(f"WHOIS overlaps found: {len(whois_overlaps)}")
    for overlap in whois_overlaps:
        print(f"  - {overlap['domain_a']} vs {overlap['domain_b']}: "
              f"same_registrar={overlap['same_registrar']}, "
              f"same_registrant_org={overlap['same_registrant_org']}")

    # --- Hosting correlation ---
    shared_ips = cluster_by_shared_ip(DOMAIN_SAMPLE)
    shared_subnets = cluster_by_subnet(DOMAIN_SAMPLE)

    print(f"\nShared exact IPs: {len(shared_ips)}")
    for ip, doms in shared_ips.items():
        print(f"  - {ip}: {doms}")

    print(f"Shared /24 subnets: {len(shared_subnets)}")
    for subnet, doms in shared_subnets.items():
        print(f"  - {subnet}: {doms}")

    # --- Certificate transparency ---
    print(f"\nChecking certificate overlap ({len(_unique_pairs(DOMAIN_SAMPLE))} pairs)...")
    cert_overlaps = []
    for domain_a, domain_b in _unique_pairs(DOMAIN_SAMPLE):
        comparison = compare_certificates(domain_a, domain_b)
        if comparison["shared_certificate_found"]:
            cert_overlaps.append(comparison)

    print(f"Certificate overlaps found: {len(cert_overlaps)}")
    for overlap in cert_overlaps:
        print(f"  - {overlap['domain_a']} vs {overlap['domain_b']}: {overlap['shared_domains']}")

    # --- Analytics fingerprinting ---
    print(f"\nFingerprinting {len(DOMAIN_SAMPLE)} sites...")
    fingerprints = []
    for domain in DOMAIN_SAMPLE:
        try:
            fingerprints.append(fingerprint_site(f"https://{domain}"))
        except Exception as error:
            logger.warning("Could not fingerprint %s: %s", domain, error)

    analytics_overlaps = []
    for fp_a, fp_b in _unique_pairs(fingerprints):
        comparison = compare_fingerprints(fp_a, fp_b)
        if comparison["shared_tracking_ids"] or comparison["same_favicon"]:
            analytics_overlaps.append(comparison)

    print(f"Analytics/favicon overlaps found: {len(analytics_overlaps)}")
    for overlap in analytics_overlaps:
        print(f"  - {overlap['url_a']} vs {overlap['url_b']}: "
              f"tracking={overlap['shared_tracking_ids']}, favicon={overlap['same_favicon']}")


if __name__ == "__main__":
    main()
