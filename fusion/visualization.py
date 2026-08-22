"""
Interactive network graph visualization for SNDOIF results.

Renders the ownership graph plus fusion confidence scores as a single
self-contained interactive HTML file (drag, zoom, hover) using pyvis --
the deliverable specified in the project synopsis: 'nodes represent
entities and edges represent the type and strength of evidence linking
them, giving a due-diligence analyst a single visual view.'
"""

import logging

import networkx as nx
from pyvis.network import Network

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CONFIDENCE_COLORS = {
    "high": "#e63946",   # red -- strongest, most attention-worthy
    "low": "#f4a261",    # orange -- worth a look, but weaker evidence
}


def build_visualization(
    graph: nx.DiGraph,
    scored_pairs: list[dict],
    output_path: str = "sndoif_network.html",
) -> str:
    """Render the ownership graph as an interactive HTML visualization,
    with fusion-scored company pairs highlighted by confidence level.

    Args:
        graph: A graph from ownership_graph.build_graph().
        scored_pairs: Output of fusion.scoring.score_all_pairs() --
            used to color and label the strongest relationships.
        output_path: Filename for the generated HTML file.

    Returns:
        The output_path, for convenience when chaining calls.
    """
    net = Network(height="800px", width="100%", directed=True, notebook=False)

    for node, attrs in graph.nodes(data=True):
        node_type = attrs.get("node_type", "person")
        if node_type == "company":
            net.add_node(node, label=node, color="#457b9d", shape="box", title=f"Company: {node}")
        else:
            net.add_node(node, label=node, color="#a8dadc", shape="dot", title=f"Person/PSC: {node}")

    for source, target, attrs in graph.edges(data=True):
        role = attrs.get("role", "")
        net.add_edge(source, target, title=f"{role}", color="#cccccc")

    # Overlay fusion-scored pairs as thick, colored edges directly
    # between the two companies, so high/low confidence relationships
    # stand out visually against the plain officer/PSC edges above.
    for pair in scored_pairs:
        # Defensive: a scored pair may reference a company not present
        # in this (possibly focused/ego) graph -- add it as a bare
        # node first rather than crashing, so a partial/focused view
        # can still show the fusion-scored connection.
        existing_nodes = net.get_nodes()
        for company in (pair["company_a"], pair["company_b"]):
            if company not in existing_nodes:
                net.add_node(company, label=company, color="#457b9d", shape="box")
                existing_nodes.append(company)

        color = CONFIDENCE_COLORS.get(pair["confidence"], "#cccccc")
        tooltip = (
            f"Confidence: {pair['confidence'].upper()}\n"
            f"Ownership evidence: {pair['has_ownership_evidence']}\n"
            f"Infrastructure evidence: {pair['has_infrastructure_evidence']}"
        )
        net.add_edge(
            pair["company_a"], pair["company_b"],
            color=color, width=4, title=tooltip,
        )

    net.show_buttons(filter_=["physics"])
    net.write_html(output_path)

    logger.info("Wrote interactive visualization to %s", output_path)
    return output_path


if __name__ == "__main__":
    from ownership.companies_house import build_ownership_records
    from ownership.ownership_graph import build_graph, entity_pairs_with_shared_person
    from fusion.scoring import score_all_pairs

    company_sample = ["09446231", "08804411", "00000006", "13211214", "07209813", "11465966", "10970586"]

    records = build_ownership_records(company_sample)
    graph = build_graph(records)
    ownership_pairs = entity_pairs_with_shared_person(graph)

    company_names = [r.company_name for r in records]
    scored_pairs = score_all_pairs(company_names, ownership_pairs, [])

    path = build_visualization(graph, scored_pairs)
    print(f"\nOpen this file in your browser: {path}")
