"""
Client for the ICIJ Offshore Leaks bulk data (nodes-entities.csv and
relationships.csv from the official ICIJ Offshore Leaks database).

This module is responsible ONLY for loading and searching the leaked
data. It does not know anything about Companies House, sanctions
screening, or red-flag logic -- those live in other modules.
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Path to the ICIJ data folder, relative to the project root. Using
# pathlib.Path (rather than a plain string) gives us an object with
# useful path-joining and cross-platform behaviour built in.
DATA_DIR = Path("data/icij")
ENTITIES_FILE = DATA_DIR / "nodes-entities.csv"
RELATIONSHIPS_FILE = DATA_DIR / "relationships.csv"


def search_entities_by_name(query: str) -> list[dict[str, Any]]:
    """Search ICIJ Offshore Leaks entities by (partial, case-insensitive) name.

    Args:
        query: A search string, e.g. "Mossack Fonseca". Matches any
            entity whose name contains this string, regardless of case.

    Returns:
        A list of dicts, one per matching entity, with keys matching
        the CSV columns (node_id, name, jurisdiction, sourceID, etc.).
        Returns an empty list if nothing matches.
    """
    logger.info("Loading entities from %s", ENTITIES_FILE)

    # low_memory=False avoids pandas guessing column types chunk-by-chunk
    # on a large file, which can otherwise produce inconsistent dtypes
    # and a noisy warning -- we'd rather load it consistently in one pass.
    entities = pd.read_csv(ENTITIES_FILE, low_memory=False)

    # na=False tells pandas to treat missing (NaN) names as "no match"
    # instead of raising an error -- some rows have blank names.
    mask = entities["name"].str.contains(query, case=False, na=False)
    matches = entities[mask]

    logger.info("Found %d entities matching '%s'", len(matches), query)

    # .to_dict(orient="records") converts a DataFrame into a list of
    # plain dicts, one per row -- exactly the shape the rest of your
    # project expects, matching how companies_house.py returns data.
    return matches.to_dict(orient="records")


def get_entity_subgraph(node_id: str) -> list[dict[str, Any]]:
    """Fetch all relationships directly connected to a given entity.

    An entity's "subgraph" here means every relationship row where this
    node_id appears as either the start or the end of the relationship --
    i.e. everything this entity is directly linked to (other entities,
    officers, intermediaries, or addresses) in the leaked data.

    Args:
        node_id: The ICIJ node_id of the entity, as found via
            search_entities_by_name().

    Returns:
        A list of dicts, one per relationship row involving this
        node_id, with keys matching relationships.csv columns
        (node_id_start, node_id_end, rel_type, link, etc.).
    """
    logger.info("Loading relationships from %s", RELATIONSHIPS_FILE)

    relationships = pd.read_csv(RELATIONSHIPS_FILE, low_memory=False)

    mask = (relationships["node_id_start"] == node_id) | (
        relationships["node_id_end"] == node_id
    )
    matches = relationships[mask]

    logger.info("Found %d relationships for node_id %s", len(matches), node_id)

    return matches.to_dict(orient="records")


if __name__ == "__main__":
    results = search_entities_by_name("Mossack Fonseca")

    print(f"\nTop matches:")
    for entity in results[:5]:
        print(f"- {entity['name']} ({entity['node_id']}) - {entity['jurisdiction']}")

    if results:
        first_node_id = results[0]["node_id"]
        subgraph = get_entity_subgraph(first_node_id)
        print(f"\n{results[0]['name']} has {len(subgraph)} direct relationships")
        for rel in subgraph[:5]:
            print(f"  {rel['link']} -> {rel['node_id_end']}")