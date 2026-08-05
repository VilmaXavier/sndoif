# SNDOIF — Shell Network Detection through Ownership-Infrastructure Fusion

A joint project combining corporate ownership analysis with technical infrastructure
correlation to detect hidden relationships between shell companies, for third-party
due diligence and AML/compliance use cases.

## Project Structure

- `ownership/` — Ownership & Compliance Layer (this repo owner's half). Complete.
- `infrastructure/` — Infrastructure Correlation Layer (teammate's half). In progress.
- `fusion/` — Combines evidence from both layers into a single confidence score. Not yet started.

## Ownership & Compliance Layer — Status: Complete

Four modules, fully working and tested against real data:

- `ownership/companies_house.py` — Client for the UK Companies House API.
  Fetches company profiles, officers, and PSC (beneficial ownership) data.
  Includes `build_ownership_records()`, which normalizes a batch of
  companies into `OwnershipRecord` objects and skips failures gracefully.

- `ownership/icij_leaks.py` — Loads the ICIJ Offshore Leaks bulk CSV data
  (entities and relationships). Supports name search and one-hop relationship
  lookups. Validated against real Panama Papers data.

- `ownership/sanctions_check.py` — Fuzzy-matches officer/PSC names against
  the free, public OFAC Specially Designated Nationals (SDN) list, including
  known aliases. Uses `rapidfuzz` for efficient one-vs-many matching.

- `ownership/ownership_graph.py` — Builds a directed graph (people to
  companies) with `networkx` and detects red flags: shared directors
  across multiple companies, circular ownership, and PSCs registered in
  FATF high-risk jurisdictions.

`main.py` runs the full pipeline end-to-end against a real UK company sample.

## Setup

1. Clone this repository
2. Create a virtual environment: `python -m venv venv`
3. Activate it:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and add your own Companies House API key
   (free, instant approval at developer.company-information.service.gov.uk)
6. Download the ICIJ Offshore Leaks CSV bundle from offshoreleaks.icij.org
   and the OFAC SDN list from sanctionslist.ofac.treas.gov, placing them in
   `data/icij/` and `data/ofac/` respectively (not included in this repo
   due to file size; both are free, public datasets)

## Running the pipeline

`python main.py`

## Running tests

`pytest`

## Known limitations

- People are identified by name alone across Companies House records, since
  Companies House does not expose a unique person identifier for privacy
  reasons. Two different real people sharing a name will currently be
  treated as the same graph node. This has been observed in practice on
  real data during testing.
- Cross-referencing ICIJ Offshore Leaks entity names to specific Companies
  House registrations by name proved unreliable in practice, illustrating
  the kind of identity obfuscation this project is designed to detect.
- The FATF high-risk jurisdiction list is a snapshot and should be
  re-checked against FATF's current published lists periodically.
