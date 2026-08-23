"""
Tests for the Flask frontend routes. Uses Flask's test client and
mocks the slow, network-dependent pipeline functions (Companies House,
sanctions, infrastructure checks) so these tests run fast and don't
depend on external services being available.
"""

from unittest.mock import patch

import pytest

from frontend.app import app
from ownership.companies_house import OwnershipRecord


@pytest.fixture
def client():
    """A Flask test client -- simulates HTTP requests without starting
    a real server. pytest automatically passes this into any test
    function that names it as a parameter.
    """
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_index_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Shell Network Detection" in response.data


def test_search_with_empty_company_number_shows_error(client):
    response = client.post("/search", data={"company_number": ""})
    assert response.status_code == 200
    assert b"Please enter a company number" in response.data


def test_search_by_name_with_empty_query_shows_error(client):
    response = client.post("/search-by-name", data={"query": ""})
    assert response.status_code == 200
    assert b"Please enter a company name" in response.data


@patch("frontend.app.build_ownership_records")
def test_search_with_unknown_company_number_shows_error(mock_build_records, client):
    # Simulate the pipeline returning no matching record for the
    # searched number -- e.g. an invalid number, or a Companies House
    # lookup failure that build_ownership_records() already handled
    # gracefully (returning fewer records than requested).
    mock_build_records.return_value = []

    response = client.post("/search", data={"company_number": "00000000"})

    assert response.status_code == 200
    assert b"Could not find company number" in response.data


@patch("frontend.app.screen_beneficial_owners")
@patch("frontend.app.build_ownership_records")
def test_search_with_known_company_shows_results(mock_build_records, mock_screen, client):
    # Fake a single successful OwnershipRecord, as if Companies House
    # returned real data for this company number.
    mock_build_records.return_value = [
        OwnershipRecord(
            company_number="09446231",
            company_name="MONZO BANK LIMITED",
            company_status="active",
            officers=[{"name": "Test Officer", "officer_role": "director"}],
            psc=[],
        )
    ]
    mock_screen.return_value = []  # no sanctions matches

    response = client.post("/search", data={"company_number": "09446231"})

    assert response.status_code == 200
    assert b"MONZO BANK LIMITED" in response.data
    assert b"No sanctions matches found" in response.data


@patch("frontend.app.search_companies_by_name")
def test_search_by_name_shows_candidate_list(mock_search, client):
    mock_search.return_value = [
        {"company_number": "13227665", "title": "DELIVEROO LIMITED", "company_status": "active"},
    ]

    response = client.post("/search-by-name", data={"query": "Deliveroo"})

    assert response.status_code == 200
    assert b"DELIVEROO LIMITED" in response.data
    assert b"13227665" in response.data
