# SNDOIF — Shell Network Detection through Ownership-Infrastructure Fusion

   A joint project combining corporate ownership analysis with technical infrastructure
   correlation to detect hidden relationships between shell companies, for third-party
   due diligence and AML/compliance use cases.

   This repository is under active development.

   ## Project Structure

   - `ownership/` — Ownership & Compliance Layer (beneficial ownership, sanctions/PEP
     screening, red-flag detection). Owned by the compliance lead.
   - `infrastructure/` — Infrastructure Correlation Layer (WHOIS, SSL, hosting, analytics
     fingerprinting). Owned by the cybersecurity lead.
   - `fusion/` — Combines evidence from both layers into a single confidence score
     (built jointly).

   ## Setup

   1. Clone this repository
   2. Create a virtual environment: `python -m venv venv`
   3. Activate it:
      - Windows: `venv\Scripts\activate`
      - Mac/Linux: `source venv/bin/activate`
   4. Install dependencies: `pip install -r requirements.txt`
   5. Copy `.env.example` to `.env` and fill in your own API keys (see below)

   ## Status

   Project scaffolding in progress. Ownership & Compliance Layer modules are being
   built incrementally.