"""
End-to-end pipeline entry point for the Ownership & Compliance Layer.

Runs the full chain: fetch ownership data from Companies House, screen
officers/PSCs against OFAC sanctions data, build the ownership graph,
and report red flags. This is the script your teammate's fusion layer
will eventually call into (or you'll export this data for them).
"""

import logging

from ownership.companies_house import build_ownership_records
from ownership.ownership_graph import (
    build_graph,
    detect_red_flags,
    entity_pairs_with_shared_person,
)
from ownership.sanctions_check import screen_beneficial_owners

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Your real entity sample. Start small and verified; grow toward your
# full 10-15 as you confirm more company numbers with your teammate.
COMPANY_SAMPLE = [
    "09446231",  # Monzo Bank Limited
    "08804411",  # Revolut Ltd
    "00000006",  # Marine and General Mutual Life Assurance Society (dissolved, old)
]


def main() -> None:
    """Run the full ownership & compliance pipeline on the sample."""
    logger.info("Building ownership records for %d companies", len(COMPANY_SAMPLE))
    records = build_ownership_records(COMPANY_SAMPLE)

    # Gather every officer/PSC name across the whole sample, so we
    # screen once against sanctions data rather than repeatedly.
    all_names: list[str] = []
    for record in records:
        all_names.extend(officer["name"] for officer in record.officers)
        all_names.extend(psc["name"] for psc in record.psc if psc.get("name"))

    logger.info("Screening %d names against OFAC sanctions data", len(all_names))
    sanctions_matches = screen_beneficial_owners(all_names)

    graph = build_graph(records)
    red_flags = detect_red_flags(graph)
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

    print(f"\nEntity pairs sharing a person (for fusion handoff): {len(shared_pairs)}")
    for pair in shared_pairs[:10]:  # just preview the first 10
        print(f"  - {pair['company_a']} <-> {pair['company_b']} via {pair['shared_person']}")


if __name__ == "__main__":
    main()