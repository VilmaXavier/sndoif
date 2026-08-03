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

    # Fail loudly and immediately if the request was not successful,
    # instead of silently returning bad or partial data.
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

    # The API wraps the actual list of officers inside an "items" key,
    # alongside metadata like total counts -- we only care about "items".
    return data["items"]


if __name__ == "__main__":
    profile = get_company_profile("00000006")
    print(profile["company_name"])
    print(profile["company_status"])

    officers = get_officers("00000006")
    print(f"Found {len(officers)} officers")
    for officer in officers:
        print(officer["name"], "-", officer["officer_role"])