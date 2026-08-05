"""
Ownership graph construction and red-flag detection.

Builds a directed graph connecting people (officers and PSCs) to the
companies they are linked to, based on OwnershipRecord data from
companies_house.py. Detects structural red flags: shared directors
across multiple companies, circular ownership, and high-risk
jurisdictions. This module does not fetch any data itself -- it only
operates on OwnershipRecord objects already built elsewhere.
"""

import logging
from typing import Any

import networkx as nx

from ownership.companies_house import OwnershipRecord

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# A person appearing as officer/PSC across this many or more companies
# in the sample is flagged as a shared-director red flag. Starting
# point, tunable based on how many false positives come back on real
# data -- same principle as the sanctions match threshold.
SHARED_DIRECTOR_THRESHOLD = 3


def build_graph(records: list[OwnershipRecord]) -> nx.DiGraph:
    """Build a directed graph linking people to the companies they control.

    Each officer or PSC becomes a node, each company becomes a node,
    and a directed edge is added from person -> company for every
    officer/PSC relationship found. Edge direction represents "this
    person has a role at this company."

    Args:
        records: OwnershipRecord objects, typically the output of
            build_ownership_records().

    Returns:
        A networkx DiGraph with person and company nodes, and edges
        carrying a "role" attribute (e.g. "director", "psc").

    Note:
        People are identified by name alone in this version. Two
        different real people who happen to share a name will be
        treated as the same graph node -- a known limitation worth
        flagging honestly in the Week 8 report.
    """
    graph = nx.DiGraph()

    # First pass: add every company node from our own sample BEFORE
    # adding any person/PSC nodes or edges. This guarantees a
    # company's node_type can never later be overwritten by a
    # same-named PSC reference found in another record (e.g. Company A
    # appearing both as its own record AND as Company B's PSC).
    for record in records:
        graph.add_node(record.company_name, node_type="company", jurisdiction="UK")

    # Second pass: add people/PSC nodes and edges. We only set
    # node_type on a node if it doesn't already exist -- this protects
    # company nodes added above, and also protects a PSC entity that
    # turns out to also be one of our sample companies.
    for record in records:
        company_node = record.company_name

        for officer in record.officers:
            person_node = officer["name"]
            if person_node not in graph:
                graph.add_node(person_node, node_type="person")
            graph.add_edge(person_node, company_node, role="officer")

        for psc in record.psc:
            person_node = psc.get("name")
            if person_node:
                if person_node not in graph:
                    graph.add_node(person_node, node_type="psc")
                graph.add_edge(person_node, company_node, role="psc")

    logger.info(
        "Built graph with %d nodes and %d edges",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )

    return graph


def entity_pairs_with_shared_person(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """Find every pair of companies that share a common officer or PSC.

    This is the primary handoff artifact for the fusion layer: pairs of
    entities linked purely through ownership/officer evidence, before
    any infrastructure correlation is considered.

    Args:
        graph: A graph built by build_graph().

    Returns:
        A list of dicts, each describing one company pair and the
        shared person connecting them: {"company_a", "company_b",
        "shared_person"}. The same pair may appear more than once if
        multiple people connect them -- that's intentional, since each
        shared person is separate evidence.
    """
    pairs: list[dict[str, Any]] = []

    person_nodes = [
        node for node, attrs in graph.nodes(data=True)
        if attrs.get("node_type") in ("person", "psc")
    ]

    for person in person_nodes:
        # successors() gives every node this person has an outgoing
        # edge to -- i.e. every company they're linked to.
        companies = list(graph.successors(person))

        # itertools.combinations would be the "proper" tool here, but
        # for clarity while learning, we'll use explicit nested loops
        # with an index guard to avoid pairing a company with itself
        # or generating both (A, B) and (B, A) as separate pairs.
        for i in range(len(companies)):
            for j in range(i + 1, len(companies)):
                pairs.append({
                    "company_a": companies[i],
                    "company_b": companies[j],
                    "shared_person": person,
                })

    logger.info("Found %d entity pairs sharing a person", len(pairs))
    return pairs


def detect_red_flags(graph: nx.DiGraph) -> dict[str, list[dict[str, Any]]]:
    """Run all red-flag detectors over the graph.

    Args:
        graph: A graph built by build_graph().

    Returns:
        A dict with two keys:
        - "shared_directors": people appearing at or above
          SHARED_DIRECTOR_THRESHOLD companies, with their company list.
        - "circular_ownership": cycles found among company nodes only.
    """
    shared_directors: list[dict[str, Any]] = []

    person_nodes = [
        node for node, attrs in graph.nodes(data=True)
        if attrs.get("node_type") in ("person", "psc")
    ]

    for person in person_nodes:
        company_count = graph.out_degree(person)
        if company_count >= SHARED_DIRECTOR_THRESHOLD:
            shared_directors.append({
                "person": person,
                "company_count": company_count,
                "companies": list(graph.successors(person)),
            })

    # nx.simple_cycles() finds every cycle in the whole graph, which
    # would include nonsensical "cycles" through person nodes. We
    # filter down to cycles that consist entirely of company nodes,
    # since that's the only kind of cycle that represents real
    # circular ownership.
    company_nodes = {
        node for node, attrs in graph.nodes(data=True)
        if attrs.get("node_type") == "company"
    }

    all_cycles = list(nx.simple_cycles(graph))
    circular_ownership = [
        {"cycle": cycle}
        for cycle in all_cycles
        if set(cycle).issubset(company_nodes)
    ]

    logger.info(
        "Red flags: %d shared-director cases, %d circular ownership cases",
        len(shared_directors),
        len(circular_ownership),
    )

    return {
        "shared_directors": shared_directors,
        "circular_ownership": circular_ownership,
    }


if __name__ == "__main__":
    # A deliberately constructed test case, not real API data -- built
    # to exercise both red-flag detectors with a known, predictable
    # outcome, so we can verify the logic before trusting it on
    # messier real-world data.
    test_records = [
        OwnershipRecord(
            company_number="AAA",
            company_name="Company A",
            company_status="active",
            officers=[{"name": "Jane Doe", "officer_role": "director"}],
            psc=[{"name": "Company B"}],  # A is controlled by B
        ),
        OwnershipRecord(
            company_number="BBB",
            company_name="Company B",
            company_status="active",
            officers=[{"name": "Jane Doe", "officer_role": "director"}],
            psc=[{"name": "Company A"}],  # B is controlled by A -- a cycle!
        ),
        OwnershipRecord(
            company_number="CCC",
            company_name="Company C",
            company_status="active",
            officers=[{"name": "Jane Doe", "officer_role": "director"}],
            psc=[],
        ),
    ]

    graph = build_graph(test_records)

    pairs = entity_pairs_with_shared_person(graph)
    print(f"\n{len(pairs)} entity pairs sharing a person:")
    for pair in pairs:
        print(f"  {pair['company_a']} <-> {pair['company_b']} via {pair['shared_person']}")

    flags = detect_red_flags(graph)
    print(f"\nShared directors ({len(flags['shared_directors'])}):")
    for flag in flags["shared_directors"]:
        print(f"  {flag['person']}: {flag['company_count']} companies -> {flag['companies']}")

    print(f"\nCircular ownership ({len(flags['circular_ownership'])}):")
    for flag in flags["circular_ownership"]:
        print(f"  {flag['cycle']}")