"""
WHOIS domain registration lookups and overlap comparison.

Fetches WHOIS registration data for domains and compares pairs of
domains for shared registrar, registrant, or name server patterns --
a signal that two seemingly unrelated websites may have been set up
by the same person or organization. This module does not know about
SSL certificates, hosting, or analytics fingerprints -- those live in
their own modules.
"""

import logging
from typing import Any

import whois

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# WHOIS privacy services redact real data with placeholder strings
# rather than leaving fields blank. Two domains both showing the exact
# same placeholder is NOT a match -- it means neither disclosed real
# data. Treating these as equivalent to missing data prevents this
# false-positive pattern.
REDACTION_PLACEHOLDERS = {
    "REDACTED FOR PRIVACY", "DATA REDACTED", "NOT DISCLOSED",
    "PRIVATE", "WHOISGUARD PROTECTED",
}


def _is_real_value(value: Any) -> bool:
    """Return False for None or a known WHOIS privacy-redaction placeholder."""
    if value is None:
        return False
    return str(value).strip().upper() not in REDACTION_PLACEHOLDERS


def _lookup_single_domain(domain: str) -> dict[str, Any]:
    """Fetch WHOIS data for a single domain, normalized to a plain dict."""
    record = whois.whois(domain)

    def first_if_list(value: Any) -> Any:
        if isinstance(value, list):
            return value[0] if value else None
        return value

    return {
        "domain": domain,
        "registrar": first_if_list(record.registrar),
        "registrant_org": first_if_list(getattr(record, "org", None)),
        "registrant_name": first_if_list(getattr(record, "name", None)),
        "creation_date": first_if_list(record.creation_date),
        "expiration_date": first_if_list(record.expiration_date),
        "name_servers": record.name_servers if isinstance(record.name_servers, list) else (
            [record.name_servers] if record.name_servers else []
        ),
    }


def batch_lookup(domains: list[str]) -> list[dict[str, Any]]:
    """Fetch WHOIS data for a batch of domains, skipping failures gracefully."""
    results: list[dict[str, Any]] = []

    for index, domain in enumerate(domains, start=1):
        logger.info("Looking up %d of %d: %s", index, len(domains), domain)
        try:
            results.append(_lookup_single_domain(domain))
        except Exception as error:
            logger.warning("Skipping %s due to WHOIS lookup error: %s", domain, error)

    return results


def compare_domains(record_a: dict[str, Any], record_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two WHOIS records for overlap signals.

    Fields redacted by WHOIS privacy services (e.g. "REDACTED FOR
    PRIVACY") are treated as unknown, not as real matching data --
    two domains both showing the same redaction placeholder is not
    evidence of a real connection.
    """
    shared_name_servers = set(record_a["name_servers"]) & set(record_b["name_servers"])

    return {
        "domain_a": record_a["domain"],
        "domain_b": record_b["domain"],
        "same_registrar": (
            _is_real_value(record_a["registrar"])
            and record_a["registrar"] == record_b["registrar"]
        ),
        "same_registrant_org": (
            _is_real_value(record_a["registrant_org"])
            and record_a["registrant_org"] == record_b["registrant_org"]
        ),
        "shared_name_servers": list(shared_name_servers),
    }


if __name__ == "__main__":
    test_domains = ["google.com", "alphabet.com", "wikipedia.org"]

    records = batch_lookup(test_domains)

    print(f"\nFetched {len(records)} of {len(test_domains)} domains:")
    for record in records:
        print(f"  {record['domain']}: registrar={record['registrar']!r}, "
              f"org={record['registrant_org']!r}")

    print("\nPairwise comparisons:")
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            comparison = compare_domains(records[i], records[j])
            print(f"  {comparison['domain_a']} vs {comparison['domain_b']}: "
                  f"same_registrar={comparison['same_registrar']}, "
                  f"same_registrant_org={comparison['same_registrant_org']}, "
                  f"shared_name_servers={comparison['shared_name_servers']}")
