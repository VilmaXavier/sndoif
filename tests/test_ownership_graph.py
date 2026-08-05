"""
Tests for ownership_graph.py's graph construction and red-flag detection.

Uses deliberately constructed OwnershipRecord data with known, predictable
answers -- the same principle as the manual test we ran during
development, now automated and repeatable.
"""

from ownership.companies_house import OwnershipRecord
from ownership.ownership_graph import (
    build_graph,
    detect_jurisdiction_red_flags,
    detect_red_flags,
    entity_pairs_with_shared_person,
)


def _make_test_records() -> list[OwnershipRecord]:
    """Build the same known-answer test case used during development:
    a director shared across 3 companies, and a 2-company circular
    ownership loop between Company A and Company B.
    """
    return [
        OwnershipRecord(
            company_number="AAA",
            company_name="Company A",
            company_status="active",
            officers=[{"name": "Jane Doe", "officer_role": "director"}],
            psc=[{"name": "Company B"}],
        ),
        OwnershipRecord(
            company_number="BBB",
            company_name="Company B",
            company_status="active",
            officers=[{"name": "Jane Doe", "officer_role": "director"}],
            psc=[{"name": "Company A"}],
        ),
        OwnershipRecord(
            company_number="CCC",
            company_name="Company C",
            company_status="active",
            officers=[{"name": "Jane Doe", "officer_role": "director"}],
            psc=[],
        ),
    ]


def test_build_graph_creates_expected_nodes_and_edges():
    records = _make_test_records()
    graph = build_graph(records)

    # 4 nodes expected: 3 companies + 1 shared person (Jane Doe).
    assert graph.number_of_nodes() == 4
    # 5 edges: Jane Doe -> each of 3 companies (3 edges), plus the
    # A->B and B->A PSC edges (2 edges) = 5 total.
    assert graph.number_of_edges() == 5


def test_build_graph_preserves_company_node_type():
    """Regression test for the node_type overwrite bug found during
    development: Company A must remain typed as "company" even though
    it also appears as Company B's PSC.
    """
    records = _make_test_records()
    graph = build_graph(records)

    assert graph.nodes["Company A"]["node_type"] == "company"
    assert graph.nodes["Company B"]["node_type"] == "company"


def test_detect_red_flags_finds_shared_director():
    records = _make_test_records()
    graph = build_graph(records)
    flags = detect_red_flags(graph)

    assert len(flags["shared_directors"]) == 1
    assert flags["shared_directors"][0]["person"] == "Jane Doe"
    assert flags["shared_directors"][0]["company_count"] == 3


def test_detect_red_flags_finds_circular_ownership():
    records = _make_test_records()
    graph = build_graph(records)
    flags = detect_red_flags(graph)

    assert len(flags["circular_ownership"]) == 1
    cycle = set(flags["circular_ownership"][0]["cycle"])
    assert cycle == {"Company A", "Company B"}


def test_entity_pairs_with_shared_person_finds_all_pairs():
    records = _make_test_records()
    graph = build_graph(records)
    pairs = entity_pairs_with_shared_person(graph)

    # 3 companies sharing one person -> 3 unique pairs (A-B, A-C, B-C).
    assert len(pairs) == 3


def test_detect_jurisdiction_red_flags_no_high_risk_jurisdiction():
    """None of the test records have a PSC in a FATF high-risk
    jurisdiction, so this should return an empty list.
    """
    records = _make_test_records()
    flags = detect_jurisdiction_red_flags(records)

    assert flags == []


def test_detect_jurisdiction_red_flags_flags_high_risk_country():
    record = OwnershipRecord(
        company_number="XXX",
        company_name="Risky Co",
        company_status="active",
        officers=[],
        psc=[{
            "name": "Suspicious Holdings Ltd",
            "identification": {"country_registered": "Iran"},
        }],
    )

    flags = detect_jurisdiction_red_flags([record])

    assert len(flags) == 1
    assert flags[0]["jurisdiction"] == "Iran"
    assert flags[0]["company_name"] == "Risky Co"