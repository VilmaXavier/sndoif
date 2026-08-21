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
handle this gracefully rather than failing on the first hiccup.
"""

import logging
import time
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CRTSH_URL = "https://crt.sh/"
MAX_RETRIES = 3


def get_san_domains(domain: str) -> list[dict[str, Any]]:
    """Fetch certificate records for a domain from crt.sh, including
    every other domain name (SAN) each certificate also covers.

    Retries up to MAX_RETRIES times with increasing delays if crt.sh
    is temporarily overloaded or slow to respond (502/503 errors,
    read timeouts) -- this is common behaviour for this free service
    under load, not a sign of a broken domain or query.

    Args:
        domain: A domain name, e.g. "example.com".

    Returns:
        A list of dicts, one per certificate found, each with the
        certificate's id, issuer name, and the full set of domain
        names (SANs) it covers -- deduplicated. Returns an empty list
        if crt.sh still fails after all retries, rather than crashing.
    """
    params = {"q": domain, "output": "json"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(CRTSH_URL, params=params, timeout=30)
            response.raise_for_status()
            break
        except requests.RequestException as error:
            # RequestException is the common parent class for every
            # network-related failure requests can raise -- bad status
            # codes (HTTPError), timeouts (Timeout), connection drops
            # (ConnectionError), etc. Catching it here means all of
            # these trigger the same retry-with-backoff behaviour,
            # instead of only handling one specific failure type.
            if attempt == MAX_RETRIES:
                logger.warning(
                    "crt.sh failed for %s after %d attempts: %s",
                    domain, MAX_RETRIES, error,
                )
                return []
            wait_seconds = 2 ** attempt  # 2s, then 4s, then 8s
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
    """Check whether two domains have ever shared a certificate.

    Args:
        domain_a: First domain to compare.
        domain_b: Second domain to compare.

    Returns:
        A dict: {"domain_a", "domain_b", "shared_certificate_found",
        "shared_domains"}. shared_domains lists every domain name that
        appeared alongside domain_a or domain_b in an overlapping
        certificate's SAN list -- i.e. other domains potentially
        administered by the same party.
    """
    certs_a = get_san_domains(domain_a)
    # Being polite to crt.sh's free public service: a short pause
    # between requests avoids hammering it, especially important since
    # we don't have an API key/rate-limit agreement with them at all.
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
    # Using a smaller/less heavily-certificated domain than google.com
    # for the single-domain demo, to reduce load on crt.sh's free service.
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
