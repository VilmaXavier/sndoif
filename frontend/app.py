"""
SNDOIF -- minimal web frontend.

Supports searching by company name (via Companies House's search
endpoint, showing a list of candidates to choose from) or by an exact
company number (skipping straight to analysis). Runs the real
ownership pipeline live, checks it against the existing entity sample
for shared-person and red-flag connections, and displays results plus
two embedded interactive graphs: a focused view and a full view.
"""

import logging
import os

import networkx as nx
from flask import Flask, render_template, request

from fusion.scoring import score_all_pairs
from fusion.visualization import build_visualization
from ownership.companies_house import build_ownership_records, search_companies_by_name
from ownership.ownership_graph import (
    build_graph,
    detect_jurisdiction_red_flags,
    detect_red_flags,
    entity_pairs_with_shared_person,
)
from ownership.sanctions_check import screen_beneficial_owners

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

BASE_SAMPLE = [
    "09446231", "08804411", "00000006",
    "13211214", "07209813", "11465966", "10970586",
]

GRAPH_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(GRAPH_OUTPUT_DIR, exist_ok=True)


@app.route("/", methods=["GET"])
def index():
    """The search form page."""
    return render_template("index.html")


@app.route("/search-by-name", methods=["POST"])
def search_by_name():
    """Search Companies House by name, show a list of candidates to pick from."""
    query = request.form.get("query", "").strip()

    if not query:
        return render_template("index.html", error="Please enter a company name.")

    logger.info("Searching by name: %s", query)
    results = search_companies_by_name(query)

    return render_template("name_results.html", query=query, results=results)


@app.route("/search", methods=["POST"])
def search():
    """Run the pipeline on the submitted company number and show results."""
    company_number = request.form.get("company_number", "").strip()

    if not company_number:
        return render_template("index.html", error="Please enter a company number.")

    logger.info("Searching company number: %s", company_number)

    all_numbers = list(dict.fromkeys(BASE_SAMPLE + [company_number]))
    records = build_ownership_records(all_numbers)

    searched_record = next(
        (r for r in records if r.company_number == company_number), None
    )
    if searched_record is None:
        return render_template(
            "index.html",
            error=f"Could not find company number '{company_number}' "
                  f"(invalid number, or Companies House lookup failed).",
        )

    sanctions_matches = screen_beneficial_owners(
        [o["name"] for o in searched_record.officers]
        + [p["name"] for p in searched_record.psc if p.get("name")]
    )

    graph = build_graph(records)
    red_flags = detect_red_flags(graph)
    jurisdiction_flags = detect_jurisdiction_red_flags(records)
    ownership_pairs = entity_pairs_with_shared_person(graph)

    company_names = [r.company_name for r in records]
    scored_pairs = score_all_pairs(company_names, ownership_pairs, [])

    relevant_pairs = [
        p for p in scored_pairs
        if searched_record.company_name in (p["company_a"], p["company_b"])
    ]
    relevant_shared_directors = [
        f for f in red_flags["shared_directors"]
        if searched_record.company_name in f["companies"]
    ]

    if searched_record.company_name in graph:
        focused_graph = nx.ego_graph(graph, searched_record.company_name, radius=2, undirected=True)
    else:
        focused_graph = graph

    focused_filename = f"graph_focused_{company_number}.html"
    full_filename = f"graph_full_{company_number}.html"

    build_visualization(
        focused_graph, relevant_pairs,
        output_path=os.path.join(GRAPH_OUTPUT_DIR, focused_filename),
    )
    build_visualization(
        graph, scored_pairs,
        output_path=os.path.join(GRAPH_OUTPUT_DIR, full_filename),
    )

    return render_template(
        "results.html",
        company_name=searched_record.company_name,
        company_number=company_number,
        company_status=searched_record.company_status,
        officer_count=len(searched_record.officers),
        psc_count=len(searched_record.psc),
        sanctions_matches=sanctions_matches,
        shared_directors=relevant_shared_directors,
        jurisdiction_flags=[
            f for f in jurisdiction_flags
            if f["company_name"] == searched_record.company_name
        ],
        scored_pairs=relevant_pairs,
        focused_filename=focused_filename,
        full_filename=full_filename,
    )


if __name__ == "__main__":
    app.run(debug=True)
