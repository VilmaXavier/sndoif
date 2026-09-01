"""
End-to-end pipeline entry point for the Ownership & Compliance Layer.

Runs the full chain: fetch ownership data from Companies House, screen
officers/PSCs against OFAC sanctions data, build the ownership graph,
and report red flags.
"""

import logging

from ownership.companies_house import build_ownership_records
from ownership.ownership_graph import (
    build_graph,
    detect_jurisdiction_red_flags,
    detect_red_flags,
    entity_pairs_with_shared_person,
)
from ownership.sanctions_check import screen_beneficial_owners

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

COMPANY_SAMPLE = [
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


def main() -> None:
    """Run the full ownership & compliance pipeline on the sample."""
    logger.info("Building ownership records for %d companies", len(COMPANY_SAMPLE))
    records = build_ownership_records(COMPANY_SAMPLE)

    all_names: list[str] = []
    for record in records:
        all_names.extend(officer["name"] for officer in record.officers)
        all_names.extend(psc["name"] for psc in record.psc if psc.get("name"))

    logger.info("Screening %d names against OFAC sanctions data", len(all_names))
    sanctions_matches = screen_beneficial_owners(all_names)

    graph = build_graph(records)
    red_flags = detect_red_flags(graph)
    jurisdiction_flags = detect_jurisdiction_red_flags(records)
    shared_pairs = entity_pairs_with_shared_person(graph)

    print("\n" + "=" * 60)
    print("SNDOIF OWNERSHIP & COMPLIANCE LAYER -- PIPELINE SUMMARY")
    print("=" * 60)

    print(f"\nCompanies processed: {len(records)} of {len(COMPANY_SAMPLE)}")
    for record in records:
        print(f"  - {record.company_name} ({record.company_number}): "
              f"{len(record.officers)} officers, {len(record.psc)} PSC")

    print(f"\nSanctions matches: {len(sanctions_matches)}")
    for match in sanctions_matches:
        print(f"  - {match['screened_name']} ~ {match['matched_name']} "
              f"(score {match['score']:.1f})")

    print(f"\nShared-director red flags: {len(red_flags['shared_directors'])}")
    for flag in red_flags["shared_directors"]:
        print(f"  - {flag['person']}: {flag['company_count']} companies")

    print(f"\nCircular ownership red flags: {len(red_flags['circular_ownership'])}")
    for flag in red_flags["circular_ownership"]:
        print(f"  - {flag['cycle']}")

    print(f"\nJurisdiction red flags: {len(jurisdiction_flags)}")
    for flag in jurisdiction_flags:
        print(f"  - {flag['company_name']}: PSC {flag['psc_name']} registered in {flag['jurisdiction']}")

    print(f"\nEntity pairs sharing a person (for fusion handoff): {len(shared_pairs)}")
    for pair in shared_pairs:
        print(f"  - {pair['company_a']} <-> {pair['company_b']} via {pair['shared_person']}")


if __name__ == "__main__":
    main()
