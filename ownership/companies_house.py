"""
Client for the UK Companies House REST API.

This module is responsible ONLY for talking to Companies House and
returning plain Python data structures (dicts/lists). It does not know
anything about sanctions screening, red-flag logic, or graphs -- those
live in other modules, downstream of this one.
"""

import os
from typing import Any

import requests
from dotenv import load_dotenv

# Load variables from .env into the environment as soon as this module
# is imported, so COMPANIES_HOUSE_API_KEY becomes available via os.getenv().
load_dotenv()

BASE_URL = "https://api.company-information.service.gov.uk"


def get_company_profile(company_number: str) -> dict[str, Any]:
    """Fetch basic company profile data for a single UK company.

    Args:
        company_number: The Companies House company registration number,
            e.g. "00000006". Leading zeros matter -- Companies House
            numbers are fixed-width strings, not integers.

    Returns:
        A dictionary containing the company's profile data as returned
        by Companies House (company name, status, registered address,
        incorporation date, etc.).

    Raises:
        requests.HTTPError: If Companies House returns a non-200 status
            code (e.g. 404 if the company number doesn't exist, 401 if
            the API key is missing or invalid).
    """
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")

    url = f"{BASE_URL}/company/{company_number}"

    response = requests.get(url, auth=(api_key, ""))
    response.raise_for_status()

    return response.json()


def get_officers(company_number: str) -> list[dict[str, Any]]:
    """Fetch the list of officers (directors, secretaries, etc.) for a company.

    Args:
        company_number: The Companies House company registration number.

    Returns:
        A list of dictionaries, one per officer, as returned by Companies
        House. Each dict typically includes keys like "name",
        "officer_role", "appointed_on", and "nationality".

    Raises:
        requests.HTTPError: If Companies House returns a non-200 status code.
    """
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")

    url = f"{BASE_URL}/company/{company_number}/officers"

    response = requests.get(url, auth=(api_key, ""))
    response.raise_for_status()

    data = response.json()

    return data["items"]


def get_psc(company_number: str) -> list[dict[str, Any]]:
    """Fetch Persons with Significant Control (beneficial ownership) data.

    PSC records may represent an individual person, a corporate entity
    that controls the company, or a legal statement (e.g. "no PSC could
    be identified"). Not every company has PSC data -- older companies
    predating the 2016 PSC requirement, or companies with no PSC filed,
    commonly return no records at all. That absence is itself meaningful
    for due-diligence purposes, so we treat it as a normal case rather
    than an error.

    Args:
        company_number: The Companies House company registration number.

    Returns:
        A list of PSC record dictionaries. Returns an empty list if the
        company has no PSC data on file (Companies House responds with
        a 404 in this case, which we treat as "no data" rather than
        a failure).

    Raises:
        requests.HTTPError: For any failure other than "no PSC data",
            e.g. 401 for a bad API key.
    """
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")

    url = f"{BASE_URL}/company/{company_number}/persons-with-significant-control"

    response = requests.get(url, auth=(api_key, ""))

    # A 404 here specifically means "this company has no PSC data" --
    # not a broken request. We treat that as a normal, valid outcome
    # (an empty list) instead of letting raise_for_status() blow up.
    if response.status_code == 404:
        return []

    response.raise_for_status()

    data = response.json()

    return data["items"]


if __name__ == "__main__":
    profile = get_company_profile("09446231")
    print(profile["company_name"])
    print(profile["company_status"])

    officers = get_officers("09446231")
    print(f"Found {len(officers)} officers")

    psc_records = get_psc("09446231")
    print(f"Found {len(psc_records)} PSC records")
    for psc in psc_records:
        # Not every PSC record has the same fields -- .get() returns
        # None instead of raising an error if a key is missing, which
        # matters here since corporate PSCs won't have "nationality".
        print(psc.get("name"), "-", psc.get("nationality"))