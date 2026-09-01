"""
Certificate Transparency (CT) log lookups via crt.sh.

Detects SSL certificate reuse across domains: if two domains have ever
been covered by the same certificate (appearing together in that
certificate's Subject Alternative Names list), that is strong, direct
evidence they were administered by the same person or organization --
much stronger than a shared registrar or shared hosting provider alone.

crt.sh is a free, community-run service and is prone to timeouts and
502 errors under load, especially for high-traffic domains with many
historical certificates. get_san_domains() retries with backoff to
handle this gracefully, and results are cached since certificate
history for a domain changes infrequently.
"""

import logging
import time
from typing import Any

import requests

from infrastructure.cache import cached

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CRTSH_URL = "https://crt.sh/"
MAX_RETRIES = 3


@cached()
def get_san_domains(domain: str) -> list[dict[str, Any]]:
    """Fetch certificate records for a domain from crt.sh, including
    every other domain name (SAN) each certificate also covers.

    Retries up to MAX_RETRIES times with increasing delays if crt.sh
    is temporarily overloaded or slow to respond. Results are cached,
    since crt.sh has proven unreliable across repeated testing, and
    certificate history rarely changes within a caching window.

    Args:
        domain: A domain name, e.g. "example.com".

    Returns:
        A list of dicts, one per certificate found. Returns an empty
        list if crt.sh still fails after all retries.
    """
    params = {"q": domain, "output": "json"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(CRTSH_URL, params=params, timeout=30)
            response.raise_for_status()
            break
        except requests.RequestException as error:
            if attempt == MAX_RETRIES:
                logger.warning(
                    "crt.sh failed for %s after %d attempts: %s",
                    domain, MAX_RETRIES, error,
                )
                return []
            wait_seconds = 2 ** attempt
            logger.info(
                "crt.sh error for %s (attempt %d/%d), retrying in %ds",
                domain, attempt, MAX_RETRIES, wait_seconds,
            )
            time.sleep(wait_seconds)

    if not response.text.strip():
        return []

    raw_entries = response.json()

    certs_by_id: dict[int, dict[str, Any]] = {}

    for entry in raw_entries:
        cert_id = entry["id"]
        if cert_id not in certs_by_id:
            certs_by_id[cert_id] = {
                "id": cert_id,
                "issuer_name": entry.get("issuer_name"),
                "sans": set(entry.get("name_value", "").split("\n")),
            }
        else:
            certs_by_id[cert_id]["sans"].update(entry.get("name_value", "").split("\n"))

    results = []
    for cert in certs_by_id.values():
        cert["sans"] = sorted(cert["sans"])
        results.append(cert)

    logger.info("Found %d unique certificates for %s", len(results), domain)
    return results


def compare_certificates(domain_a: str, domain_b: str) -> dict[str, Any]:
    """Check whether two domains have ever shared a certificate."""
    certs_a = get_san_domains(domain_a)
    time.sleep(1)
    certs_b = get_san_domains(domain_b)

    sans_a = {san for cert in certs_a for san in cert["sans"]}
    sans_b = {san for cert in certs_b for san in cert["sans"]}

    shared_domains = sans_a & sans_b

    return {
        "domain_a": domain_a,
        "domain_b": domain_b,
        "shared_certificate_found": len(shared_domains) > 0,
        "shared_domains": sorted(shared_domains),
    }


if __name__ == "__main__":
    domain = "wikimediafoundation.org"
    certs = get_san_domains(domain)

    print(f"\n{domain}: found {len(certs)} unique certificates")
    for cert in certs[:3]:
        print(f"  cert {cert['id']} ({cert['issuer_name']}): {len(cert['sans'])} SAN entries")
        print(f"    sample: {cert['sans'][:5]}")

    print("\nComparing github.com vs gitlab.com (expect no shared certificate):")
    comparison = compare_certificates("github.com", "gitlab.com")
    print(f"  shared_certificate_found={comparison['shared_certificate_found']}")
    print(f"  shared_domains={comparison['shared_domains']}")
