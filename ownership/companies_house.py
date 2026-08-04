"""
Client for the UK Companies House REST API.

This module is responsible ONLY for talking to Companies House and
returning plain Python data structures. It does not know anything about
sanctions screening, red-flag logic, or graphs -- those live in other
modules, downstream of this one.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.company-information.service.gov.uk"

# A basic logging setup: INFO level means we'll see progress messages
# and warnings, but not overly verbose debug detail. Every module that
# uses logging typically creates its own named logger like this.
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class OwnershipRecord:
    """A normalized, single-company record combining profile, officers,
    and PSC (beneficial ownership) data from Companies House.

    This is the shape that downstream code (ownership_graph.py, and the
    shared fusion layer) should rely on -- not raw Companies House JSON.
    """

    company_number: str
    company_name: str
    company_status: str
    officers: list[dict[str, Any]] = field(default_factory=list)
    psc: list[dict[str, Any]] = field(default_factory=list)


def get_company_profile(company_number: str) -> dict[str, Any]:
    """Fetch basic company profile data for a single UK company."""
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
    url = f"{BASE_URL}/company/{company_number}"

    response = requests.get(url, auth=(api_key, ""))
    response.raise_for_status()

    return response.json()


def get_officers(company_number: str) -> list[dict[str, Any]]:
    """Fetch the list of officers (directors, secretaries, etc.) for a company."""
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
    url = f"{BASE_URL}/company/{company_number}/officers"

    response = requests.get(url, auth=(api_key, ""))
    response.raise_for_status()

    return response.json()["items"]


def get_psc(company_number: str) -> list[dict[str, Any]]:
    """Fetch Persons with Significant Control (beneficial ownership) data."""
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
    url = f"{BASE_URL}/company/{company_number}/persons-with-significant-control"

    response = requests.get(url, auth=(api_key, ""))

    if response.status_code == 404:
        return []

    response.raise_for_status()

    return response.json()["items"]


def build_ownership_records(company_numbers: list[str]) -> list[OwnershipRecord]:
    """Build normalized ownership records for a batch of companies.

    For each company number, fetches profile, officers, and PSC data and
    combines them into one OwnershipRecord. If fetching data for a given
    company fails for any reason (bad number, network error, API error),
    that company is skipped with a logged warning -- the rest of the
    batch still completes. This matters because a single bad entry in a
    10-15 company sample should not prevent processing the other 14.

    Args:
        company_numbers: A list of Companies House company numbers to
            process, e.g. ["09446231", "00000006"].

    Returns:
        A list of OwnershipRecord objects, one per company that was
        successfully fetched. Companies that failed are omitted, not
        included as partial/broken records.
    """
    records: list[OwnershipRecord] = []

    for index, company_number in enumerate(company_numbers, start=1):
        logger.info(
            "Processing company %d of %d: %s",
            index,
            len(company_numbers),
            company_number,
        )

        try:
            profile = get_company_profile(company_number)
            officers = get_officers(company_number)
            psc = get_psc(company_number)
        except requests.HTTPError as error:
            logger.warning(
                "Skipping company %s due to API error: %s",
                company_number,
                error,
            )
            continue

        record = OwnershipRecord(
            company_number=company_number,
            company_name=profile["company_name"],
            company_status=profile["company_status"],
            officers=officers,
            psc=psc,
        )
        records.append(record)

    return records


if __name__ == "__main__":
    sample = ["09446231", "00000006", "99999999"]  # last one is invalid, on purpose
    results = build_ownership_records(sample)

    print(f"\nSuccessfully built {len(results)} of {len(sample)} records:")
    for record in results:
        print(f"- {record.company_name} ({record.company_number}): "
              f"{len(record.officers)} officers, {len(record.psc)} PSC records")