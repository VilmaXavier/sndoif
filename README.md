# SNDOIF — Shell Network Detection through Ownership-Infrastructure Fusion

A due-diligence tool that fuses UK corporate ownership analysis with technical
infrastructure correlation to detect hidden relationships between companies —
built entirely solo (both the compliance/ownership layer and the
cybersecurity/OSINT infrastructure layer), including a full web frontend.

## What it does

Search or compare UK companies to check:
- **Ownership**: shared directors/PSCs, circular ownership, FATF jurisdiction risk
- **Sanctions**: fuzzy-matched against the OFAC SDN list (primary names + aliases)
- **Infrastructure**: WHOIS, SSL certificate reuse, shared hosting, tracking-ID/favicon overlap
- **Fusion**: combines both types of evidence into a HIGH / LOW / NONE confidence score

Every successful search permanently joins a growing "known entities" set, so the
tool's coverage improves the more it's used, rather than staying frozen at a
fixed starting sample.

## Web app

Run `python -m frontend.app` and visit http://127.0.0.1:5000 for:
- **Search by name or number** — runs the full pipeline live, shows an interactive
  network graph (focused view + full network toggle), downloadable as PDF
- **Compare two companies directly** — shared people, sanctions, and infrastructure
  overlap between two specific companies, with a "guess domain" helper and
  downloadable PDF report

## Project structure

- `ownership/` — Ownership & Compliance Layer
  - `companies_house.py` — Companies House API client (profile, officers, PSC,
    name search). `build_ownership_records()` batches and normalizes results.
  - `icij_leaks.py` — ICIJ Offshore Leaks bulk CSV search and relationship lookup.
  - `sanctions_check.py` — OFAC SDN fuzzy matching (rapidfuzz, primary + alias names).
  - `ownership_graph.py` — networkx graph of people-to-companies; detects shared
    directors, circular ownership, FATF jurisdiction risk.
  - `entity_store.py` — persistent JSON store of known companies, grows with use.
  - `domain_guesser.py` — heuristic + DNS-verified domain guessing from a company name.
  - `report_export.py` — PDF report generation (reportlab) for search and comparison results.
- `infrastructure/` — Infrastructure Correlation Layer
  - `whois_lookup.py` — WHOIS comparison, with privacy-redaction-placeholder handling.
  - `cert_transparency.py` — SSL certificate SAN overlap via crt.sh, retry/backoff.
  - `hosting_correlation.py` — shared IP / subnet clustering via DNS.
  - `analytics_fingerprint.py` — tracking ID and favicon hash extraction/comparison.
  - `cache.py` — time-based caching for slow external lookups.
- `fusion/`
  - `scoring.py` — combines ownership + infrastructure evidence into a confidence score.
  - `visualization.py` — interactive pyvis network graph generation.
- `frontend/` — Flask web app (search, compare, name lookup, PDF export).
- `main.py` / `infrastructure_main.py` / `project_main.py` — CLI pipelines
  for each layer individually or the full combined pipeline.

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

- `python -m frontend.app` — the web app (recommended)
- `python main.py` / `python infrastructure_main.py` / `python project_main.py` — CLI pipelines
- `pytest` — full test suite (ownership, infrastructure, cache, frontend)

## Real findings from testing

- **HIGH confidence**: Ocado Group Plc &harr; Ocado Retail Limited — 10 shared
  directors AND a shared domain registrar, a genuine, corroborated joint-venture
  relationship.
- **LOW confidence**: Deliveroo Limited &harr; Ocado Group Plc — one shared
  non-executive director (Claudia Arney), a real but weaker signal needing
  manual review.
- **NONE**: Monzo Bank &harr; Starling Bank — two genuine competitors, correctly
  showing no connection.
- **Documented false positives**: a name-collision between two unrelated
  companies sharing an officer name; shared "big name" registrars/CDNs
  (MarkMonitor, Cloudflare) that are common and meaningless; WHOIS privacy
  redaction placeholders that looked like a real match until fixed; generic
  corporate-naming overlap in sanctions screening ("X Group Holdings" vs
  "Y Group Holdings").

## Known limitations

- People are identified by name alone in the ownership graph (no unique person
  ID is exposed by Companies House) — a real name-collision false positive was
  observed in testing.
- Cross-referencing ICIJ entity names to Companies House registrations by name
  proved unreliable in practice.
- crt.sh (certificate transparency) is a free community service that failed in
  the majority of test runs during development (502/timeout errors) —
  independent of retry logic. A production system would need a paid CT log API
  or self-hosted mirror.
- Domain guessing is a heuristic, not authoritative: it can return the same
  domain for two different but related companies (observed with Ocado Group
  and Ocado Retail); a same-domain safeguard prevents this producing a false
  positive, but the guess itself is not guaranteed correct.
- The FATF high-risk jurisdiction list is a static snapshot and should be
  re-checked against FATF's current published list periodically.
- The sanctions match threshold (85) misses translated/reworded name variants
  (e.g. "Banco Nacional de Cuba" vs "National Bank of Cuba", score 74.4).
- Fusion can only score a pair when both companies have a known/guessable
  domain; the ownership layer is UK Companies House-specific and cannot be
  used for companies registered outside the UK.
