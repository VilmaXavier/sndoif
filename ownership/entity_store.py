"""
Persistent store of "known" company numbers -- the set every new
search is compared against for shared-director, sanctions, and
infrastructure connections.

Starts seeded with an initial sample, but grows every time a search
succeeds: the searched company is added to the known set, so future
searches can discover connections to it too. This mirrors how a real
investigator's case file grows over time, rather than staying frozen
at a fixed starting list.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_FILE = Path(__file__).parent.parent / "known_entities.json"

# The original starting sample, used only the first time this file is
# created -- after that, the JSON file itself is the source of truth,
# and this list is never consulted again.
SEED_COMPANIES = [
    "09446231",  # Monzo Bank Limited
    "08804411",  # Revolut Ltd
    "00000006",  # Marine and General Mutual Life Assurance Society (dissolved, old)
    "13211214",  # Wise Plc
    "07209813",  # Wise Payments Limited
    "11465966",  # Deliveroo International Ltd
    "10970586",  # Deliveroo SP Ltd
    "13227665",  # Deliveroo Limited (parent/holding)
    "09092149",  # Starling Bank Limited
    "07098618",  # Ocado Group Plc
    "03875000",  # Ocado Retail Limited (JV with Marks & Spencer)
]


def load_known_companies() -> list[str]:
    """Load the current list of known company numbers.

    If the store file doesn't exist yet, it's created and seeded with
    SEED_COMPANIES -- this only happens once, the first time the app
    runs on a given machine.

    Returns:
        A list of Companies House company numbers.
    """
    if not STORE_FILE.exists():
        logger.info("No entity store found -- seeding with %d initial companies", len(SEED_COMPANIES))
        _save(SEED_COMPANIES)
        return list(SEED_COMPANIES)

    with open(STORE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def add_known_company(company_number: str) -> None:
    """Add a company number to the known set, if not already present.

    Args:
        company_number: The Companies House number to add.
    """
    known = load_known_companies()
    if company_number not in known:
        known.append(company_number)
        _save(known)
        logger.info("Added %s to known entities (now %d total)", company_number, len(known))


def _save(companies: list[str]) -> None:
    """Write the known companies list to the store file."""
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(companies, f, indent=2)
