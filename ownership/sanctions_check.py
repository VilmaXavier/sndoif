"""
Sanctions and PEP screening for officers and beneficial owners.

Fuzzy-matches names from Companies House officer/PSC records against
the OFAC Specially Designated Nationals (SDN) list -- a free, public,
no-signup-required US government sanctions list. This module is
responsible ONLY for the matching logic -- it does not know about
ownership graphs or red-flag scoring, which live in ownership_graph.py.
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("data/ofac")
SDN_FILE = DATA_DIR / "SDN.CSV"
ALT_FILE = DATA_DIR / "ALT.CSV"

# OFAC publishes these files with no header row, so we name the
# columns ourselves based on OFAC's published data specification.
SDN_COLUMNS = [
    "ent_num", "sdn_name", "sdn_type", "program", "title",
    "call_sign", "vess_type", "tonnage", "grt", "vess_flag",
    "vess_owner", "remarks",
]
ALT_COLUMNS = ["ent_num", "alt_num", "alt_type", "alt_name", "alt_remarks"]

MATCH_SCORE_THRESHOLD = 85


def name_similarity(name_a: str, name_b: str) -> float:
    """Compute a similarity score (0-100) between two names."""
    normalized_a = name_a.strip().lower()
    normalized_b = name_b.strip().lower()
    return fuzz.token_sort_ratio(normalized_a, normalized_b)


def _load_sanctions_names() -> pd.DataFrame:
    """Load and combine primary SDN names and their known aliases into
    one flat table of (ent_num, name, source) rows to screen against.

    Screening against aliases as well as primary names matters because
    a sanctioned entity may appear in company filings under a name
    variant that only shows up in OFAC's "aka" records, not the
    primary listing.
    """
    sdn = pd.read_csv(SDN_FILE, header=None, names=SDN_COLUMNS, quotechar='"')
    alt = pd.read_csv(ALT_FILE, header=None, names=ALT_COLUMNS, quotechar='"')

    primary = sdn[["ent_num", "sdn_name"]].rename(columns={"sdn_name": "name"})
    primary["source"] = "primary"

    aliases = alt[["ent_num", "alt_name"]].rename(columns={"alt_name": "name"})
    aliases["source"] = "alias"

    combined = pd.concat([primary, aliases], ignore_index=True)

    # Some rows have missing/blank names (pandas represents these as
    # NaN, a float -- not a string), which would crash our string
    # comparison later. Drop them here, once, so every downstream
    # consumer of this DataFrame can safely assume "name" is always
    # a real string.
    combined = combined.dropna(subset=["name"])

    return combined


def screen_beneficial_owners(names: list[str]) -> list[dict[str, Any]]:
    """Screen a list of names against the OFAC SDN list (primary + aliases).

    Args:
        names: Officer/PSC names to screen, e.g. gathered from
            OwnershipRecord.officers and OwnershipRecord.psc.

    Returns:
        A list of dicts describing every match at or above
        MATCH_SCORE_THRESHOLD, each with the screened name, the
        matched sanctions entry, the ent_num, whether it matched a
        primary name or an alias, and the similarity score. Empty
        list if nothing was flagged.
    """
    logger.info("Loading OFAC SDN + alias data")
    sanctions_names = _load_sanctions_names()

    flagged: list[dict[str, Any]] = []

    for name in names:
        for _, row in sanctions_names.iterrows():
            score = name_similarity(name, row["name"])
            if score >= MATCH_SCORE_THRESHOLD:
                flagged.append({
                    "screened_name": name,
                    "matched_name": row["name"],
                    "ent_num": row["ent_num"],
                    "match_source": row["source"],
                    "score": score,
                })

    logger.info("Screened %d names, found %d flagged matches", len(names), len(flagged))
    return flagged


if __name__ == "__main__":
    # A deliberately mixed test set: one exact real SDN name, one
    # slightly misspelled variant of a real entry, and one clearly
    # unrelated name that should NOT be flagged.
    test_names = [
        "AEROCARIBBEAN AIRLINES",
        "Aero Caribbean",
        "John Smith",
    ]

    results = screen_beneficial_owners(test_names)

    print(f"\n{len(results)} flagged matches:")
    for match in results:
        print(
            f"- {match['screened_name']!r} matched {match['matched_name']!r} "
            f"(ent_num {match['ent_num']}, {match['match_source']}, "
            f"score {match['score']:.1f})"
        )