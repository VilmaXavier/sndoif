# SNDOIF — Shell Network Detection through Ownership-Infrastructure Fusion

**Live demo:** https://sndoif.onrender.com
**Repository:** https://github.com/VilmaXavier/sndoif

A due-diligence prototype that fuses UK corporate ownership analysis with
technical infrastructure correlation to detect hidden relationships between
companies — corroborating two independent evidence types (who legally
controls an entity, and what technical infrastructure it shares with others)
rather than relying on either alone.

Originally scoped as an 8-week, two-person project split into a Compliance
layer and a Cybersecurity/OSINT layer. Both layers, the fusion logic, and the
full web application were ultimately designed and built solely by one person.

---

## 1. Motivation

Shell companies are used to obscure beneficial ownership by structuring
entities to appear unrelated on paper, even when they are operationally
connected. Standard due-diligence checks corporate registries and sanctions
lists for ownership evidence. Separately, cybersecurity/OSINT practice uses
technical infrastructure (shared hosting, SSL certificates, tracking IDs) to
link "unrelated" web properties. This project combines both signal types: a
relationship corroborated by **both** ownership evidence and infrastructure
evidence is treated as materially stronger than either alone.

This is not a hypothetical problem. In August 2026, The Guardian reported
that over 3,000 UK shell companies — registered under innocuous trade
descriptions such as hairdressers, beauticians, and mini-marts — were linked
to an estimated £464 million in suspect funds moving through the UK
financial system.

## 2. Architecture

\\\
Ownership & Compliance Layer          Infrastructure Correlation Layer
────────────────────────────          ─────────────────────────────
Companies House API                   WHOIS registration data
ICIJ Offshore Leaks                   Certificate Transparency (crt.sh)
OFAC sanctions screening              DNS / shared hosting
Ownership graph (networkx)            Tracking ID / favicon fingerprinting
        │                                       │
        └───────────────┬───────────────────────┘
                         ▼
                  Fusion Scoring
        (HIGH / LOW / NONE confidence per entity pair)
                         │
                         ▼
              Flask Web Application
   (search, direct comparison, interactive graphs, PDF export)
\\\

### 2.1 Ownership & Compliance Layer (\ownership/\)
| Module | Responsibility |
|---|---|
| \companies_house.py\ | UK Companies House API client — company profile, officers, PSC (beneficial ownership), and name search. Normalizes results into \OwnershipRecord\ objects. |
| \icij_leaks.py\ | Loads and searches the ICIJ Offshore Leaks bulk dataset (entities + relationships), validated against real Panama Papers records. |
| \sanctions_check.py\ | Fuzzy name matching (rapidfuzz) against the OFAC Specially Designated Nationals list — primary names and known aliases. |
| \ownership_graph.py\ | Builds a directed graph (networkx) of people to companies. Detects shared directors across multiple companies, circular ownership, and FATF high-risk-jurisdiction PSCs. |
| \entity_store.py\ | Persistent store of every company successfully searched — the comparison set grows with use rather than staying fixed. |
| \domain_guesser.py\ | DNS-verified heuristic for guessing a company's likely domain from its name. |
| \eport_export.py\ | Generates downloadable PDF reports for both single-company and comparison results. |

### 2.2 Infrastructure Correlation Layer (\infrastructure/\)
| Module | Responsibility |
|---|---|
| \whois_lookup.py\ | WHOIS registration comparison — shared registrar, registrant organization, name servers. Explicitly treats privacy-redaction placeholders ("REDACTED FOR PRIVACY") as unknown, not as a real match. |
| \cert_transparency.py\ | SSL certificate reuse detection via Certificate Transparency logs (crt.sh) — a direct SAN overlap is strong evidence of common administration. Includes retry-with-backoff for this service's frequent instability. |
| \hosting_correlation.py\ | Shared IP address / subnet clustering via DNS resolution. |
| \nalytics_fingerprint.py\ | Extracts and compares Google Analytics/Tag Manager/Facebook Pixel IDs and favicon hashes embedded in site source code. |
| \cache.py\ | Time-based caching for slow external lookups, with explicit handling to avoid caching failed/empty results. |

### 2.3 Fusion (\usion/\)
\scoring.py\ combines ownership-layer entity pairs with infrastructure-layer
overlaps. A pair supported by **both** evidence types scores **HIGH**
confidence; a pair supported by only one scores **LOW** confidence and is
flagged for manual review; a pair with no evidence in either layer is not
reported at all. \isualization.py\ renders the ownership graph and scored
pairs as an interactive HTML network graph (pyvis).

## 3. Web Application

Run \python -m frontend.app\ (or visit the live demo) for:
- **Search by name or number** — runs the pipeline against a single company
  live, checks it against every previously-searched company, and shows an
  interactive network graph (a focused view of just that company's
  neighborhood, or the full known network), downloadable as a PDF report.
- **Compare two companies directly** — shared directors/PSCs, sanctions
  exposure, and (optionally) infrastructure overlap between two specific
  companies, with a "guess domain" helper and a downloadable PDF report.

Every successful search or comparison permanently adds the involved
companies to a persistent, growing "known entities" set — the tool's
coverage improves the more it is used, rather than being frozen at a fixed
starting sample.

## 4. Real Findings

The following were produced by running the live tool against real UK
companies, not synthetic test data.

| Pair | Confidence | Evidence |
|---|---|---|
| Ocado Group Plc ↔ Ocado Retail Limited | **HIGH** | 10 shared directors (a genuine joint venture with Marks & Spencer) **and** a shared domain registrar (CSC Corporate Domains) |
| Deliveroo Limited ↔ Ocado Group Plc | **LOW** | One shared non-executive director (Claudia Arney) — a real but single-source signal requiring manual confirmation |
| NEWS 2026 LIMITED ↔ Ocado Group / Ocado Retail | **LOW** | A shared historical director, Stephen Wayne Daintith — independently verified as Ocado's actual CFO and a former CFO of News International, DMGT, and Rolls-Royce. This connection was discovered entirely by the tool's inclusion of *historical*, not just current, officer records, and was not anticipated in advance. |
| Monzo Bank Limited ↔ Starling Bank Limited | **NONE** | Two genuine competitors — correctly shows no connection |

### Documented false-positive patterns
Real testing surfaced several concrete failure modes, each addressed in code:
1. **Name collisions** — a person with a common name (e.g. "Fiona McBain")
   appearing as an officer of two entirely unrelated companies is
   indistinguishable from a real link, since Companies House does not expose
   a unique person identifier.
2. **Shared "big name" infrastructure** — two unrelated, large companies
   sharing a well-known registrar (MarkMonitor) or CDN (Cloudflare) is common
   and meaningless; this is a materially weaker signal than a small/obscure
   shared provider.
3. **WHOIS privacy redaction** — two domains both showing the literal string
   "REDACTED FOR PRIVACY" is not a real match; this was initially a bug
   (fixed) that produced a false match between Monzo and Revolut.
4. **Generic corporate naming** — fuzzy sanctions matching can score two
   unrelated companies highly if both names contain generic terms like
   "Group Holdings Limited" (observed: 86.7 similarity between two
   completely unrelated companies).

## 5. Validated Design Choices

Rather than treating detection thresholds as fixed defaults, they were
tested empirically against known cases:
- **Shared-director threshold = 3**: at threshold 2, the known name-collision
  false positive is included; at threshold 3, it is correctly excluded while
  the known real corporate-group pattern (Deliveroo executives, 3 companies)
  is still detected.
- **Sanctions match threshold = 85**: reliably catches spelling/typo variants
  (94–97% similarity) and correctly rejects unrelated names (~22%), but
  misses translated/reworded names (e.g. "Banco Nacional de Cuba" vs.
  "National Bank of Cuba", 74.4% similarity) — a known limitation of
  string-similarity matching alone.

## 6. Known Limitations

- People are identified by name alone in the ownership graph; Companies
  House does not expose a unique person identifier, so name collisions
  between unrelated individuals are indistinguishable from real links.
- Cross-referencing ICIJ Offshore Leaks entity names to specific Companies
  House registrations by name proved unreliable in practice — itself an
  illustration of the identity obfuscation this project is designed to
  detect.
- Certificate Transparency lookups via crt.sh failed in the majority of test
  runs during development (502/timeout/404 errors), independent of the
  retry logic implemented. A production system would need a paid CT log API
  or a self-hosted mirror.
- Domain-guessing is a heuristic, not authoritative, and can return the same
  domain for two different but related companies (observed with Ocado Group
  and Ocado Retail); a same-domain safeguard prevents this from silently
  producing a false positive.
- The FATF high-risk jurisdiction list is a static snapshot in the code and
  should be re-checked against FATF's current published list periodically.
- The ownership layer is specific to the UK Companies House registry and
  cannot be used to investigate companies registered in other jurisdictions.
- Fusion can only score a pair when both companies have a known or
  guessable domain.

## 7. Testing

- \	ests/test_ownership_graph.py\ — graph construction and red-flag detection
- \	ests/test_infrastructure.py\ — comparison logic and subnet math
- \	ests/test_cache.py\ — caching behavior, including a regression test for
  a bug where failed lookups were incorrectly cached
- \	ests/test_frontend.py\ — Flask routes, using the test client and mocked
  pipeline functions so tests run without real network calls

Run the full suite with \pytest\.

## 8. Setup & Running Locally

1. Clone the repository and create a virtual environment:
   \\\
   python -m venv venv
   venv\\Scripts\\activate   (Windows)   /   source venv/bin/activate   (Mac/Linux)
   pip install -r requirements.txt
   \\\
2. Copy \.env.example\ to \.env\ and add a free Companies House API key
   (developer.company-information.service.gov.uk).
3. OFAC sanctions data is included in the repository. For the ICIJ Offshore
   Leaks module specifically, download the bulk CSV bundle from
   offshoreleaks.icij.org into \data/icij/\ (not included due to file size).
4. Run the web app: \python -m frontend.app\, then visit
   http://127.0.0.1:5000.

## 9. Technology

Python, Flask, pandas, networkx, rapidfuzz, pyvis, reportlab, python-whois,
BeautifulSoup, requests. Deployed on Render.

## 10. Future Work

- A name-search-to-domain resolution step for infrastructure checks that
  does not depend on manual entry or heuristic guessing.
- Persisting the known-entities store and comparison history in a real
  database rather than a JSON file, for larger-scale use.
- Integrating an additional free sanctions/PEP source (e.g. the UN
  Consolidated List) alongside OFAC for broader coverage.
- A self-hosted or paid Certificate Transparency data source to remove the
  dependency on crt.sh's availability.
