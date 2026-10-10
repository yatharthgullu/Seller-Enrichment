# Seller Enrichment — IndiaMART Voice AI Hackathon 2.0

Turns a seller's own raw KYC documents (invoice, sign board, Udyam
certificate, cancelled cheque) into a confidence-scored, IM-schema profile —
instead of scraping external sites, this fuses documents the seller has
*already submitted*, cross-validates them against each other, and backtests
every field against IndiaMART's own verified seller records.

## Why this approach

The provided dataset (`data/raw/`) isn't just raw inputs — it's 5,000
**already-verified** seller profiles (the answer key) plus the raw KYC
documents used to build them, ~13,000 of which already carry IndiaMART's own
AI extraction (`llm_extraction` column). That makes it possible to build a
pipeline that is honestly, measurably scored against ground truth, instead of
a scraping agent whose output quality is just "looks plausible."

## Pipeline

```
so_kyc_documents.csv (llm_extraction JSON)
        │
        ▼
 src/fusion.py        — collect candidate values per field from every
                         document a seller has, cluster near-duplicates,
                         weighted-vote a winner, assign confidence
        │
        ▼
 src/gstin_rules.py    — deterministic rules from the public GSTIN scheme:
                          state code → state, PAN entity char → legal status
        │
        ▼
 src/address_parser.py — pincode regex + gazetteer city/state match against
                          ref_cities.csv / ref_states.csv (not the answer key)
        │
        ▼
 src/taxonomy.py       — map invoice products / Udyam NIC text onto
                          IndiaMART's 696-category taxonomy
        │
        ▼
 src/validate.py        — score every field against so_sellers.csv /
                          so_seller_categories.csv (ground truth, read only
                          here — fusion/taxonomy never see it)
        │
        ▼
 src/calibration.py    — fit raw confidence → empirical accuracy per field
                          (see "Confidence calibration" below)
        │
        ▼
 outputs/*.json  →  app.py (Streamlit: dashboard + editable seller profile,
                             CSV/JSON export with confidence scores)
```

### What's "extracted" vs. "looked up"

- **Extracted & scored** (the actual ML work): company name, GSTIN, address
  → city/state/pincode, legal status, category. Every one of these is
  validated against the verified answer key.
- **Authoritative lookup, not probabilistic** (realistic production
  pattern): once a seller's GSTIN is resolved, owner/partner names and
  designation come from a GST registry lookup (simulated here via the
  dataset's `gst_partner_names` / `contact_designation`) — not re-extracted
  and scored, because a government registry response isn't a prediction.

## Results (3,000 sellers with ≥1 extractable document)

| Field | Match rate | Basis |
|---|---|---|
| Company name | 86.7% (avg similarity 91.3) | fuzzy match, doc fusion |
| GSTIN entity-type char | 90.7% | validated via privacy-safe `gstin_num_6th_char` |
| Legal status | 89.4% | deterministic GSTIN PAN-char rule |
| State | 91.5% | gazetteer match / GSTIN state code |
| Pincode | 73.7% | regex + gazetteer |
| City | 68.2% | gazetteer match |
| Field coverage | 92.6% | avg 5.55 / 6 target fields auto-filled |
| Category top-5 precision | 9.1% (n=456) | keyword/stem overlap vs 696-category taxonomy |

Catalog-health bonus: 154 sellers with catalogue gaps (missing price/specs)
had invoice-extracted products that could auto-fill them (346 priced line
items recovered).

Run `python scripts/run_pipeline.py` to regenerate `outputs/*.json`.

## Confidence calibration

The fusion engine's raw confidence (source-reliability weight +
cross-document agreement) turned out to **rank** fields correctly — binning
raw confidence from the backtest shows accuracy climbing monotonically from
66% (≤0.5) to 95%+ (≥0.8) — but it's conservative on an **absolute** scale:
a raw score of 0.55 was still correct ~85% of the time. A literal "accept
above 0.8" policy on the raw score would therefore under-trust the pipeline.

`scripts/run_pipeline.py` fits a bin-wise raw-confidence → empirical-accuracy
mapping from exactly the (confidence, correct?) pairs the backtest produces,
and attaches a `calibrated_confidence` to every independently-validated
field (company name, legal status, city, state, pincode). GSTIN keeps its
raw score — we only validate its 6th character, not the full number, so
there's no full ground truth to calibrate against.

At the default 0.80 calibrated-confidence threshold: **43.1% of individual
fields** are auto-acceptable, and **259 of 3,000 sellers (8.6%)** have *all
five* validated fields clear the bar with zero manual input needed. Both
numbers (and the threshold itself) are adjustable live in the dashboard.

## Upload mode (the product, not just the backtest)

The first tab of the app takes a seller's (or many sellers') KYC documents —
CSV in the `so_kyc_documents.csv` shape, or JSON — runs the same fusion and
calibration, and triages every field: **auto-fill** (high), **confirm**
(medium), **review / fill in** (low or missing), each with a plain-English
reason. `src/enrich.py` holds the parsing, enrichment and triage; sample
inputs are in `data/samples/`. No answer key is touched in this path.

Triage adds two cross-checks on top of the calibrated score: the GSTIN
**check digit** (valid → 93.0% correct vs 77.7% when it fails; a failing
GSTIN is swapped for another document's reading if that one passes), and
GSTIN-state vs address-state agreement. A conflict only demotes a field when
the dissenting documents carry ≥ half the winner's source weight.
Backtest of the buckets: high 93.7% correct, medium 74.0% (a held-out re-test, fitting the calibration on 2,000
sellers and scoring the other 1,000 over 10 random splits, gives 92.4% for the auto-fill bucket vs 92.5%
in-sample, so there is no meaningful overfit).

## Phone confirmation (Sarvam voice agent)

Fields triage left at medium / low / missing are confirmed by a Sarvam voice agent
("IndiaMART Seller Profile Verification"). The call is placed by hand from the Sarvam
dashboard with the seller's GLID in the `glid` agent variable (the panel shows the
variables, and a cohort CSV for campaigns). Results come back by webhook, or with the
**Fetch latest calls** button, and the panel shows per field what was on file, whether
it was confirmed / corrected / collected, and the new value. **Apply** writes the
validated values into the profile. See `docs/sarvam_agent_prompt.md`.

Setup: `.env` at the project root (git-ignored) with `SARVAM_APPS_API_KEY` (Voice
Agents key), `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_AGENT_ID`;
`SARVAM_API_KEY` is only used to transliterate Hindi replies.

## Download / export

The dashboard's "Download predicted data" section exports every seller's
predicted fields **with their confidence score** as CSV (bulk) or JSON
(per-seller or full batch) — this is the hand-off a real onboarding pipeline
would consume, applying its own threshold to decide what's auto-accepted vs.
routed to a human (`src/export.py`).

## Running

```bash
# environment note: this machine's Application Control policy blocks
# pip-installed compiled wheels (pandas) but not conda ones — install
# pandas/numpy via conda, everything else (streamlit, rapidfuzz, plotly)
# via pip.
conda install -y pandas
pip install rapidfuzz streamlit plotly

python scripts/run_pipeline.py      # full 3,000-seller batch -> outputs/
streamlit run app.py                # dashboard + editable seller profile UI
```

## Known limitations (honest, for the write-up)

- Category mapping is keyword/stem overlap against 696 categories, not
  embeddings — fast and dependency-light, but weak when a seller has no
  invoice product names (456/3000 sellers had any category signal at all).
- City/pincode matching is exact-string against the gazetteer — doesn't
  correct OCR typos in locality names.
- "People" data is surfaced from an authoritative source, not independently
  verified by this pipeline — documented above as an explicit design choice,
  not an oversight.

## Run the web app

React front end (`web/`) over a FastAPI backend (`api/main.py`), one process on one port:

```bash
cd web && npm install && npm run build      # once, and after UI changes
cd .. && python -m uvicorn api.main:app --port 8000
# open http://localhost:8000
```

For UI work, run `python -m uvicorn api.main:app --port 8000` and `npm run dev` (in `web/`) and open
http://localhost:5173; it proxies `/api` to the backend. The same server receives Sarvam webhooks at
`/sarvam/webhook?token=<WEBHOOK_TOKEN>`. The older Streamlit UI (`streamlit run app.py`) still works.

## Test data

`sample_data/` holds a 10-seller test pack (fictional sellers covering every outcome: complete, confirm, collect, GSTIN misread, conflicting names, risk flag) and a guide to the input structure. Download it from the app (**Enrich sellers → Data format**) or regenerate it with `python scripts/make_sample_dataset.py --check`.
