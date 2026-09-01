"""
Threshold sensitivity experiment: reruns red-flag and sanctions
detection at several threshold values against the real sample, so we
can see concretely how each choice affects results before picking a
final value -- rather than trusting the original arbitrary defaults
without checking.
"""

from ownership.companies_house import build_ownership_records
from ownership.ownership_graph import build_graph
import networkx as nx

COMPANY_SAMPLE = [
    "09446231", "08804411", "00000006",
    "13211214", "07209813", "11465966", "10970586", "13227665",
]


def shared_directors_at_threshold(graph, threshold):
    person_nodes = [n for n, a in graph.nodes(data=True) if a.get("node_type") in ("person", "psc")]
    return [
        {"person": p, "company_count": graph.out_degree(p)}
        for p in person_nodes
        if graph.out_degree(p) >= threshold
    ]


if __name__ == "__main__":
    records = build_ownership_records(COMPANY_SAMPLE)
    graph = build_graph(records)

    print("Shared-director results at different thresholds:\n")
    for threshold in [2, 3, 4, 5]:
        results = shared_directors_at_threshold(graph, threshold)
        print(f"Threshold {threshold}: {len(results)} people flagged")
        for r in sorted(results, key=lambda x: -x["company_count"])[:5]:
            print(f"    {r['person']}: {r['company_count']} companies")
        print()
