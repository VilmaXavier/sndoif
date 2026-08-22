"""
Website analytics/tracking ID and favicon fingerprinting.

Extracts Google Analytics, Google Tag Manager, and similar tracking IDs
embedded in a website's HTML source, plus a hash of its favicon image.
Two unrelated companies sharing the exact same tracking ID or favicon
hash is strong evidence of common administration -- these identifiers
are meant to be unique per site owner, so reuse is essentially never
coincidental.
"""

import hashlib
import logging
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TRACKING_ID_PATTERNS = {
    "google_analytics_ua": re.compile(r"UA-\d{4,10}-\d{1,4}"),
    "google_analytics_ga4": re.compile(r"G-[A-Z0-9]{6,10}"),
    "google_tag_manager": re.compile(r"GTM-[A-Z0-9]{4,8}"),
    "facebook_pixel": re.compile(r"fbq\('init',\s*'(\d{10,20})'\)"),
}


def fingerprint_site(url: str) -> dict[str, Any]:
    """Fetch a site and extract tracking IDs and a favicon hash."""
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    html = response.text

    tracking_ids: dict[str, list[str]] = {}
    for name, pattern in TRACKING_ID_PATTERNS.items():
        matches = pattern.findall(html)
        if matches:
            tracking_ids[name] = list(dict.fromkeys(matches))

    favicon_hash = _get_favicon_hash(url, html)

    return {
        "url": url,
        "tracking_ids": tracking_ids,
        "favicon_hash": favicon_hash,
    }


def _get_favicon_hash(base_url: str, html: str) -> str | None:
    """Find and hash a page's favicon image.

    Handles both normal favicon URLs and inline data: URIs (some sites
    embed the favicon directly as base64-encoded image data rather
    than linking to a separate file) -- data URIs are hashed directly
    without a network fetch, since the image data is already present.
    """
    soup = BeautifulSoup(html, "html.parser")

    icon_tag = soup.find("link", rel=lambda value: value and "icon" in value.lower())
    favicon_path = icon_tag["href"] if icon_tag and icon_tag.get("href") else "/favicon.ico"

    if favicon_path.startswith("data:"):
        # The actual image bytes are base64-encoded after the comma in
        # a data URI (e.g. "data:image/svg+xml;base64,PD94bWwg...").
        # We hash the raw data URI string itself rather than decoding
        # it -- sufficient for detecting exact reuse across sites,
        # which is all we need this signal for.
        return hashlib.sha256(favicon_path.encode("utf-8")).hexdigest()

    favicon_url = urljoin(base_url, favicon_path)

    try:
        response = requests.get(favicon_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return hashlib.sha256(response.content).hexdigest()
    except requests.RequestException as error:
        logger.warning("Could not fetch favicon for %s: %s", base_url, error)
        return None


def compare_fingerprints(fingerprint_a: dict[str, Any], fingerprint_b: dict[str, Any]) -> dict[str, Any]:
    """Compare two site fingerprints for shared tracking IDs or favicon."""
    shared_tracking_ids: dict[str, list[str]] = {}
    for name in fingerprint_a["tracking_ids"]:
        ids_a = set(fingerprint_a["tracking_ids"].get(name, []))
        ids_b = set(fingerprint_b["tracking_ids"].get(name, []))
        overlap = ids_a & ids_b
        if overlap:
            shared_tracking_ids[name] = sorted(overlap)

    same_favicon = (
        fingerprint_a["favicon_hash"] is not None
        and fingerprint_a["favicon_hash"] == fingerprint_b["favicon_hash"]
    )

    return {
        "url_a": fingerprint_a["url"],
        "url_b": fingerprint_b["url"],
        "shared_tracking_ids": shared_tracking_ids,
        "same_favicon": same_favicon,
    }


if __name__ == "__main__":
    test_urls = ["https://github.com", "https://gitlab.com"]

    fingerprints = [fingerprint_site(url) for url in test_urls]

    for fp in fingerprints:
        print(f"\n{fp['url']}:")
        print(f"  tracking_ids: {fp['tracking_ids']}")
        print(f"  favicon_hash: {fp['favicon_hash']}")

    print("\nComparison:")
    comparison = compare_fingerprints(fingerprints[0], fingerprints[1])
    print(f"  shared_tracking_ids: {comparison['shared_tracking_ids']}")
    print(f"  same_favicon: {comparison['same_favicon']}")
