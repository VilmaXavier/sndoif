"""
Sanctions match-score threshold experiment: reruns fuzzy matching at
several thresholds against known real and near-miss name pairs, to
see concretely how threshold choice trades off false positives against
false negatives, rather than trusting the original default untested.
"""

from rapidfuzz import fuzz

# Known real OFAC entries and realistic name variants that might appear
# in company filings, plus a genuinely unrelated pair as a negative
# control.
test_pairs = [
    ("AEROCARIBBEAN AIRLINES", "AEROCARIBBEAN AIRLINES"),       # exact match
    ("AEROCARIBBEAN AIRLINES", "Aero Caribbean"),                # real variant (no hyphen)
    ("BANCO NACIONAL DE CUBA", "National Bank of Cuba"),         # translated variant
    ("John Smith", "Jon Smith"),                                  # common typo pattern
    ("John Smith", "Jane Doe"),                                   # unrelated (negative control)
    ("Michael Johnson", "Michael Jonson"),                        # 1-letter typo
]

if __name__ == "__main__":
    print("Score results across thresholds:\n")
    print(f"{'Pair':<55}{'Score':>8}")
    print("-" * 63)
    for name_a, name_b in test_pairs:
        score = fuzz.token_sort_ratio(name_a.lower(), name_b.lower())
        print(f"{name_a[:25]:<25} vs {name_b[:25]:<25}{score:>6.1f}")

    print("\nHow many pairs would be flagged at each threshold:")
    for threshold in [75, 80, 85, 90, 95]:
        flagged = sum(
            1 for a, b in test_pairs
            if fuzz.token_sort_ratio(a.lower(), b.lower()) >= threshold
        )
        print(f"  Threshold {threshold}: {flagged} of {len(test_pairs)} pairs flagged")
