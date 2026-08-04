"""
Sanctions and PEP screening for officers and beneficial owners.

Fuzzy-matches names from Companies House officer/PSC records against
sanctions and PEP data (OpenSanctions). This module is responsible ONLY
for the matching logic and the API call -- it does not know about
ownership graphs or red-flag scoring, which live in ownership_graph.py.
"""

import logging

from rapidfuzz import fuzz

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Matches scoring at or above this threshold are flagged for review.
# This is a starting point, not a final answer -- it should be tuned
# based on how many false positives come back against real data.
MATCH_SCORE_THRESHOLD = 85


def name_similarity(name_a: str, name_b: str) -> float:
    """Compute a similarity score between two names.

    Args:
        name_a: First name to compare.
        name_b: Second name to compare.

    Returns:
        A similarity score from 0 (completely different) to 100
        (identical), after normalizing case and surrounding whitespace.
    """
    normalized_a = name_a.strip().lower()
    normalized_b = name_b.strip().lower()

    # token_sort_ratio handles word-order differences too -- e.g.
    # "Smith, John" vs "John Smith" still scores highly, since it
    # sorts the words in each string before comparing.
    return fuzz.token_sort_ratio(normalized_a, normalized_b)


if __name__ == "__main__":
    test_pairs = [
        ("John Smith", "John Smith"),
        ("Mohammed Al-Amin", "Mohamed Al Amin"),
        ("John Smith", "Jane Doe"),
        ("Smith, John", "John Smith"),
    ]

    for name_a, name_b in test_pairs:
        score = name_similarity(name_a, name_b)
        flagged = "FLAGGED" if score >= MATCH_SCORE_THRESHOLD else "ok"
        print(f"{name_a!r} vs {name_b!r}: {score:.1f} ({flagged})")