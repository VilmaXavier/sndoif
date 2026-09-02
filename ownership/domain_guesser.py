"""
Domain guessing: derives plausible website domains from a company name
and verifies which ones actually resolve, so a user isn't required to
already know or manually look up a company's domain before running
infrastructure checks.

This is a heuristic, not a reliable lookup -- company names often
don't map cleanly to domains (trading names differ from registered
names, some companies use unrelated brand domains entirely). Verified
suggestions are still just candidates for the user to confirm, not a
guaranteed match.
"""

import logging
import re

from infrastructure.hosting_correlation import resolve_domain

logger = logging.getLogger(__name__)

# Words that commonly appear in UK company names but rarely appear in
# the company's actual domain -- stripped before generating candidates.
NOISE_WORDS = {"limited", "ltd", "plc", "group", "holdings", "the", "company", "co"}


def _normalize_name(company_name: str) -> str:
    """Strip common corporate suffixes and non-alphanumeric characters,
    leaving a bare lowercase string suitable for building a domain guess.
    """
    words = re.findall(r"[a-zA-Z0-9]+", company_name.lower())
    meaningful_words = [w for w in words if w not in NOISE_WORDS]
    return "".join(meaningful_words) if meaningful_words else "".join(words)


def guess_domains(company_name: str, verify: bool = True) -> list[str]:
    """Generate plausible domain candidates for a company name.

    Args:
        company_name: The company's registered name, e.g. "Ocado Group Plc".
        verify: If True (default), only return candidates that actually
            resolve via DNS -- filters out guesses that don't correspond
            to a real, live domain.

    Returns:
        A list of candidate domains, most likely first. Empty if no
        candidate could be generated or none resolved (when verify=True).
    """
    normalized = _normalize_name(company_name)
    if not normalized:
        return []

    candidates = [
        f"{normalized}.com",
        f"{normalized}.co.uk",
    ]

    # Also try just the first "meaningful" word alone, since some
    # companies use a shorter brand domain than their full legal name
    # (e.g. "Ocado Group Plc" -> "ocado.com", not "ocadogroup.com").
    words = re.findall(r"[a-zA-Z0-9]+", company_name.lower())
    meaningful_words = [w for w in words if w not in NOISE_WORDS]
    if meaningful_words and meaningful_words[0] != normalized:
        candidates.insert(0, f"{meaningful_words[0]}.com")

    # Deduplicate while preserving order.
    candidates = list(dict.fromkeys(candidates))

    if not verify:
        return candidates

    verified = []
    for candidate in candidates:
        if resolve_domain(candidate):
            verified.append(candidate)
        else:
            logger.info("Guessed domain %s does not resolve -- skipping", candidate)

    return verified


if __name__ == "__main__":
    test_names = [
        "Ocado Group Plc",
        "Monzo Bank Limited",
        "Deliveroo Limited",
        "Starling Bank Limited",
    ]

    for name in test_names:
        guesses = guess_domains(name)
        print(f"{name}: {guesses}")
