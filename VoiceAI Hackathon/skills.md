# Build journey — Seller Enrichment

## Approach decision
Started from the problem statement assuming an external web-scraping
approach (Google Places, website scraping, social pages). After inspecting
the actual provided dataset, pivoted: the data isn't scraping fodder, it's
5,000 already-verified seller profiles (answer key) plus the raw KYC
documents behind them, ~13k already carrying IndiaMART's own AI extraction.
That made a document-fusion-and-backtest approach both more realistic and
far more measurable than scraping — every claim in the demo is a number
computed against real ground truth, not "looks right to me."

## What we built, in order
1. `src/data_loader.py` — load the CSVs, parse `llm_extraction` JSON,
   group documents per seller.
2. `src/gstin_rules.py` — public GSTIN numbering rules (state code →
   state, PAN entity character → legal status) used as a deterministic
   sub-feature, not guessed by an LLM.
3. `src/fusion.py` — the core engine: collect every document's candidate
   values per field, cluster near-duplicates, weighted-vote a winner,
   assign confidence from source reliability + cross-document agreement.
4. `src/address_parser.py` — pincode regex + a city/state gazetteer
   matcher built from `ref_cities.csv`/`ref_states.csv` (not the answer
   key) to turn free-text invoice addresses into structured location.
5. `src/taxonomy.py` — map invoice products / Udyam NIC descriptions onto
   IndiaMART's 696-category taxonomy via a stemmed inverted index +
   rapidfuzz re-rank (not embeddings — kept it dependency-light and fast).
6. `src/validate.py` + `scripts/run_pipeline.py` — backtest every field
   against `so_sellers.csv` / `so_seller_categories.csv`.
7. `app.py` — Streamlit dashboard (dataset-level accuracy) + per-seller
   editable profile view with confidence badges, source attribution, and
   answer-key comparison toggle.
8. `src/calibration.py` + `src/export.py` — calibrate raw confidence
   against empirical backtest accuracy, and export every prediction with
   its confidence score as CSV/JSON for downstream auto-accept routing.

## Bugs found and fixed during the build
- **Fuzzy clustering merged different pincodes.** Pincode fusion initially
  reused the same fuzzy token-sort clustering as company names. "800007"
  (from the invoice/sign board) and "800001" (the bank's branch pincode on
  a cancelled cheque) are only one character apart, so they got merged into
  one cluster and the wrong value sometimes won. Fixed by adding an
  `exact=True` mode to the fusion clusterer, used for pincode and GSTIN
  (identifiers), while names/addresses still use fuzzy clustering (OCR
  noise). Pincode match rate went 72.0% → 73.7% after the fix.
- **Singular/plural mismatch broke category matching.** The taxonomy
  inverted index matched on raw tokens, so a query for "Flavour" missed the
  category "Food Flavours, ..." (plural). Added a trivial stemmer and
  switched the final score from `rapidfuzz.token_set_ratio` (which
  penalizes short queries against long category labels) to a token-overlap
  score with a fuzzy near-miss fallback.
- **Raw confidence was under-calibrated.** After wiring up a "download with
  confidence score" export, a sanity check (bin raw confidence from the
  backtest, compute actual accuracy per bin) showed the *ranking* was right
  (66%→76%→86%→93%→95% accuracy as confidence rises) but the *scale* wasn't:
  a raw 0.55 confidence field was still correct ~85% of the time, so an
  "accept above 0.8" policy on the raw score would reject far more good
  predictions than it should. Fixed by fitting a bin-wise raw→empirical-
  accuracy calibration from the same backtest data and exposing it as
  `calibrated_confidence`. Also caught that GSTIN's raw confidence (no
  independent full-number ground truth to calibrate against) was dragging
  the "all fields above threshold" seller-level metric to 0 — excluded it
  from that strict gate and tracked it separately instead.

## Environment note
This machine's Application Control policy blocked pip-installed compiled
wheels for pandas (numpy and rapidfuzz worked fine pip-installed; pandas
specifically triggered "An Application Control policy has blocked this
file" on every pip-built version tried). Installing pandas via `conda
install` instead of `pip install` resolved it — conda-channel binaries
passed the policy where PyPI wheels didn't.

## Tools used
Python, pandas, rapidfuzz, Streamlit, plotly. No external APIs, no web
scraping, no LLM calls in the core pipeline — entirely offline/local,
removing live-demo network risk. (A Sarvam voice confirmation layer is the
planned next addition for the Voice Experience scoring criterion.)
