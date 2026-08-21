"""
Hosting infrastructure correlation: shared IP and subnet detection.

Resolves domains to IP addresses via DNS (free, unlimited, no API key)
and clusters domains that share an exact IP or the same /24 subnet --
a signal that they may be hosted on the same server or by the same
hosting account. Deliberately checks free DNS-based signals first;
paid enrichment (e.g. Shodan) should only be called on IPs that
already show overlap here, to conserve limited API credits.
"""

import logging
import socket
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def resolve_domain(domain: str) -> list[str]:
    """Resolve a domain name to its IP address(es) via DNS."""
    try:
        _, _, ip_addresses = socket.gethostbyname_ex(domain)
        return ip_addresses
    except socket.gaierror as error:
        logger.warning("Could not resolve %s: %s", domain, error)
        return []


def _subnet_24(ip_address: str) -> str:
    """Return the /24 subnet for an IPv4 address."""
    parts = ip_address.split(".")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


def cluster_by_shared_ip(domains: list[str]) -> dict[str, list[str]]:
    """Group domains that resolve to the exact same IP address."""
    ip_to_domains: dict[str, list[str]] = {}

    for domain in domains:
        for ip in resolve_domain(domain):
            ip_to_domains.setdefault(ip, []).append(domain)

    shared = {ip: doms for ip, doms in ip_to_domains.items() if len(doms) >= 2}

    logger.info("Found %d shared IPs across %d domains", len(shared), len(domains))
    return shared


def cluster_by_subnet(domains: list[str]) -> dict[str, list[str]]:
    """Group domains whose IPs fall in the same /24 subnet."""
    subnet_to_domains: dict[str, list[str]] = {}

    for domain in domains:
        for ip in resolve_domain(domain):
            subnet = _subnet_24(ip)
            if domain not in subnet_to_domains.setdefault(subnet, []):
                subnet_to_domains[subnet].append(domain)

    shared = {subnet: doms for subnet, doms in subnet_to_domains.items() if len(doms) >= 2}

    logger.info("Found %d shared subnets across %d domains", len(shared), len(domains))
    return shared


if __name__ == "__main__":
    test_domains = ["github.com", "gitlab.com", "wikipedia.org", "wikimediafoundation.org"]

    print("Resolving domains:")
    for domain in test_domains:
        ips = resolve_domain(domain)
        print(f"  {domain}: {ips}")

    print("\nShared exact IPs:")
    shared_ips = cluster_by_shared_ip(test_domains)
    for ip, doms in shared_ips.items():
        print(f"  {ip}: {doms}")
    if not shared_ips:
        print("  (none)")

    print("\nShared /24 subnets:")
    shared_subnets = cluster_by_subnet(test_domains)
    for subnet, doms in shared_subnets.items():
        print(f"  {subnet}: {doms}")
    if not shared_subnets:
        print("  (none)")
