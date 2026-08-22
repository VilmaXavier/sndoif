"""
Fusion scoring: combines ownership-layer evidence with infrastructure-
layer evidence into a single confidence score per entity pair.

A relationship supported by BOTH ownership evidence (shared director,
circular ownership) AND infrastructure evidence (shared WHOIS, cert,
hosting, or tracking ID) is scored HIGH confidence -- two independent
signals corroborating each other. A relationship with only one type of
evidence is scored LOW confidence and flagged for manual review, since
a single signal alone (e.g. two companies sharing a big-name registrar)
is often coincidental, as seen repeatedly in real testing.
"""

import logging
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Maps a company name (as it appears in Companies House / the ownership
# layer) to its domain (as used in the infrastructure layer). This is
# the explicit bridge between the two layers' evidence -- built by hand
# for the current entity sample, since Companies House data does not
# include a domain field to derive this automatically.
ENTITY_DOMAIN_MAP = {
    "MONZO BANK LIMITED": "monzo.com",
    "REVOLUT LTD": "revolut.com",
    "WISE LIMITED": "wise.com",
    "WISE PAYMENTS LIMITED": "wise.com",
    "DELIVEROO INTERNATIONAL LTD": "deliveroo.co.uk",
    "DELIVEROO SP LTD": "deliveroo.co.uk",
}


def score_entity_pair(
    company_a: str,
    company_b: str,
    ownership_pairs: list[dict[str, Any]],
    infrastructure_overlaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute a fused confidence score for one pair of companies.

    Args:
        company_a: First company name (ownership layer naming).
        company_b: Second company name (ownership layer naming).
        ownership_pairs: Output of entity_pairs_with_shared_person()
            from ownership_graph.py.
        infrastructure_overlaps: A combined list of overlap dicts from
            the infrastructure layer (WHOIS, cert, hosting, analytics
            comparisons), each containing domain_a/domain_b or
            url_a/url_b fields.

    Returns:
        A dict: {"company_a", "company_b", "has_ownership_evidence",
        "has_infrastructure_evidence", "confidence", "details"}.
        confidence is one of "high", "low", or "none".
    """
    has_ownership_evidence = any(
        {pair["company_a"], pair["company_b"]} == {company_a, company_b}
        for pair in ownership_pairs
    )

    domain_a = ENTITY_DOMAIN_MAP.get(company_a)
    domain_b = ENTITY_DOMAIN_MAP.get(company_b)

    has_infrastructure_evidence = False
    if domain_a and domain_b:
        for overlap in infrastructure_overlaps:
            overlap_domains = {
                overlap.get("domain_a") or overlap.get("url_a", "").replace("https://", ""),
                overlap.get("domain_b") or overlap.get("url_b", "").replace("https://", ""),
            }
            if {domain_a, domain_b} == overlap_domains:
                has_infrastructure_evidence = True
                break

    if has_ownership_evidence and has_infrastructure_evidence:
        confidence = "high"
    elif has_ownership_evidence or has_infrastructure_evidence:
        confidence = "low"
    else:
        confidence = "none"

    return {
        "company_a": company_a,
        "company_b": company_b,
        "has_ownership_evidence": has_ownership_evidence,
        "has_infrastructure_evidence": has_infrastructure_evidence,
        "confidence": confidence,
    }


def score_all_pairs(
    companies: list[str],
    ownership_pairs: list[dict[str, Any]],
    infrastructure_overlaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score every unique pair of companies in the sample.

    Args:
        companies: List of all company names in the sample.
        ownership_pairs: Output of entity_pairs_with_shared_person().
        infrastructure_overlaps: Combined infrastructure overlap list.

    Returns:
        A list of score dicts (see score_entity_pair), one per unique
        pair, excluding pairs with no evidence of either type at all
        (confidence "none" is not included -- nothing to report).
    """
    results = []
    for i in range(len(companies)):
        for j in range(i + 1, len(companies)):
            score = score_entity_pair(
                companies[i], companies[j], ownership_pairs, infrastructure_overlaps
            )
            if score["confidence"] != "none":
                results.append(score)

    logger.info("Scored %d pairs with at least one type of evidence", len(results))
    return results


if __name__ == "__main__":
    # Deliberately constructed test case: Company A/B share BOTH types
    # of evidence (expect HIGH), Company A/C share only ownership
    # evidence (expect LOW), Company D has no evidence at all with
    # anyone (expect excluded from results).
    test_ownership_pairs = [
        {"company_a": "Company A", "company_b": "Company B", "shared_person": "Jane Doe"},
        {"company_a": "Company A", "company_b": "Company C", "shared_person": "John Smith"},
    ]
    test_infrastructure_overlaps = [
        {"domain_a": "a.com", "domain_b": "b.com"},
    ]
    test_map_backup = dict(ENTITY_DOMAIN_MAP)
    ENTITY_DOMAIN_MAP.clear()
    ENTITY_DOMAIN_MAP.update({"Company A": "a.com", "Company B": "b.com", "Company C": "c.com"})

    companies = ["Company A", "Company B", "Company C", "Company D"]
    results = score_all_pairs(companies, test_ownership_pairs, test_infrastructure_overlaps)

    print(f"\n{len(results)} pairs with evidence:")
    for r in results:
        print(f"  {r['company_a']} <-> {r['company_b']}: confidence={r['confidence']} "
              f"(ownership={r['has_ownership_evidence']}, infra={r['has_infrastructure_evidence']})")

    ENTITY_DOMAIN_MAP.clear()
    ENTITY_DOMAIN_MAP.update(test_map_backup)
