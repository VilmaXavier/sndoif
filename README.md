# SNDOIF — Shell Network Detection through Ownership-Infrastructure Fusion

Fuses corporate ownership analysis with technical infrastructure correlation to
detect hidden relationships between shell companies, for third-party due
diligence and AML/compliance use cases. Originally scoped as a two-person
project; both the Ownership & Compliance Layer and the Infrastructure
Correlation Layer were ultimately built solo.

## Project Structure

- `ownership/` — Ownership & Compliance Layer. Complete.
- `infrastructure/` — Infrastructure Correlation Layer. Complete.
- `fusion/` — Combines evidence from both layers into a confidence score. Complete.
- `main.py` — Ownership layer pipeline only.
- `infrastructure_main.py` — Infrastructure layer pipeline only.
- `project_main.py` — Full end-to-end pipeline: ownership -> infrastructure -> fusion.

## Ownership & Compliance Layer

- `ownership/companies_house.py` — UK Companies House API client (profile,
  officers, PSC/beneficial ownership). `build_ownership_records()` batches
  and normalizes into `OwnershipRecord` objects, skipping failures gracefully.
- `ownership/icij_leaks.py` — ICIJ Offshore Leaks bulk CSV search and
  relationship-subgraph lookup, validated against real Panama Papers data.
- `ownership/sanctions_check.py` — Fuzzy name matching (rapidfuzz) against
  the free OFAC SDN list (primary names + aliases).
- `ownership/ownership_graph.py` — Directed graph (networkx) of people to
  companies. Detects shared directors, circular ownership, and FATF
  high-risk-jurisdiction PSCs.

## Infrastructure Correlation Layer

- `infrastructure/whois_lookup.py` — WHOIS registration comparison, with
  explicit handling of WHOIS privacy-redaction placeholders to avoid false
  positives (a real bug found and fixed during development).
- `infrastructure/cert_transparency.py` — SSL certificate SAN overlap
  detection via crt.sh, with retry/backoff for this service's frequent
  transient failures.
- `infrastructure/hosting_correlation.py` — Shared IP / subnet clustering
  via free DNS resolution.
- `infrastructure/analytics_fingerprint.py` — Tracking ID and favicon hash
  extraction and comparison.

## Fusion

- `fusion/scoring.py` — Combines ownership-layer entity pairs with
  infrastructure-layer overlaps. A pair with BOTH types of evidence scores
  HIGH confidence; a pair with only one type scores LOW confidence and is
  flagged for manual review; pairs with no evidence are not reported.

## Setup

1. Clone this repository
2. `python -m venv venv`
3. Activate: `venv\Scripts\activate` (Windows) / `source venv/bin/activate` (Mac/Linux)
4. `pip install -r requirements.txt`
5. Copy `.env.example` to `.env`, add a free Companies House API key
   (developer.company-information.service.gov.uk)
6. Download the ICIJ Offshore Leaks CSV bundle (offshoreleaks.icij.org) into
   `data/icij/` and the OFAC SDN list (sanctionslist.ofac.treas.gov) into
   `data/ofac/` (not included in this repo due to file size)

## Running it

- `python main.py` — ownership layer only
- `python infrastructure_main.py` — infrastructure layer only
- `python project_main.py` — full pipeline with fused confidence scores
- `pytest` — full test suite (both layers)

## Known limitations

- People are identified by name alone in the ownership graph (Companies House
  exposes no unique person ID). A real name-collision false positive was
  observed in testing (an officer shared between two unrelated companies).
- Cross-referencing ICIJ entity names to Companies House registrations by
  name proved unreliable in practice.
- crt.sh (certificate transparency) is a free community service prone to
  outages and rate limiting; the pipeline handles this gracefully via retry
  with backoff, but results can vary run to run depending on its availability.
- Fusion can only score a pair when both companies have a mapped domain in
  `fusion.scoring.ENTITY_DOMAIN_MAP` — this mapping is currently built by
  hand for the sample and does not scale automatically to new entities.
- The FATF high-risk jurisdiction list is a static snapshot in the code and
  should be re-checked against FATF's current published list periodically.
