# Session handoff: Seller Enrichment (IndiaMART Voice AI Hackathon 2.0)

Read this first in a new session. No secrets are stored here; keys live in `.env` (git-ignored).

## Project
Document-fusion pipeline that turns a seller's KYC documents (invoice, sign board, Udyam
certificate, cancelled cheque) into a confidence-scored IndiaMART profile. Offline and
deterministic core; Sarvam (voice, calls, optional doc AI) layered on top.
Repo: `Seller-Enrichment` (Windows). The dataset is not in git: put the `so_*.csv` / `ref_*.csv` files in `data/raw/`.
Run the web app with `python -m uvicorn api.main:app --port 8000` and `npm run dev` in `web/` (see README).
The older Streamlit UI (`streamlit run app.py`) still works; **restart it after editing `src/`** (it caches modules).
If pip-installed pandas is blocked by Application Control, install pandas via conda.

## Pipeline (already built, unchanged this session)
`src/fusion.py` weighted-vote fusion (source weights Udyam .95 > invoice .65 > sign board .55 > cheque .45;
conf = winner_share x max_weight + 0.15 per extra agreeing doc; exact match for GSTIN/pincode) ->
`gstin_rules.py` (state code, PAN char -> legal status) -> `address_parser.py` (pincode regex + gazetteer) ->
`taxonomy.py` (category keyword match, weak) -> `validate.py` (backtest vs answer key) ->
`calibration.py` (raw -> empirical accuracy bins) -> `outputs/*.json`.
Backtest (3,000 sellers): company 86.7%, legal 89.5%, state 91.5%, pincode 73.7%, city 68.2%, category top-5 precision 9.1%.
Buckets: calibrated >= 0.8 high, >= 0.5 medium, else low.

## Built this session
1. **Upload mode** (`src/enrich.py`, first tab of `app.py`): upload CSV (so_kyc_documents shape) or JSON with
   `llm_extraction`; fuse + calibrate; **triage** each field: auto-fill / confirm / review / fill in, with reasons.
   Extras: GSTIN check-digit validation (`gstin_checksum_valid`; valid = 93.0% correct vs 77.7% failing; swaps to
   another document's reading if that passes), GSTIN-state vs address-state cross-check, conflicts only demote
   when dissent weight >= half the winner's. Backtest of buckets: high 93.7% right, medium 74.0%.
   Corrections stored in session + `outputs/corrections.json`. Export CSV/JSON. Samples in `data/samples/` (git-ignored).
2. **Voice confirmation**: the in-browser mic panel was removed. Confirmation is by Sarvam voice agent call (`src/sarvam_calls.py`); `src/voice.py` now only parses replies.
3. **Outbound phone call** (`src/outbound.py`, `scripts/webhook_server.py`, "Confirm by phone call" panel):
   POSTs to `https://apps.sarvam.ai/api/outbounds/v1/orgs/{org}/workspaces/{ws}/outbounds` (header `X-API-Key`),
   passes agent variables, gets `attempt_id`; results return ONLY via webhook (no documented status endpoint):
   `final_agent_variables`, `interaction_transcript`, echoed metadata (seller_id). Results saved to
   `outputs/calls/`; agent outputs are re-validated before they can change a field. Tested with mocks only.
   Agent prompt + variable contract: `docs/sarvam_agent_prompt.md`.
   Input vars: business_name, language, fields_to_confirm, fields_to_collect, <field>_current.
   Output vars (String): company_name_final, gstin_final, legal_status_final, city_final, state_final,
   pincode_final, call_outcome. Unconfirmed = `UNCONFIRMED`.
4. Docs: README sections added; `.gitignore` repaired (was UTF-16) and now ignores data/raw, data/samples,
   .env, outputs/*.json, outputs/corrections.json, outputs/calls/, skills.md.

## Git / GitHub
Repo `https://github.com/yatharthgullu/Seller-Enrichment`; work is on branch `feature/FrontendNew`.
`data/raw/`, `outputs/*.json`, `.env` and `.archify/` are git-ignored: real seller data and secrets must never
be committed. Check `git status --short` before every commit.

## Sarvam facts learned
- Document AI (Akshar): `/doc-ai/v1/job/digitise` and `/extract` (JSON-schema extraction), PDF/PNG/JPEG/ZIP,
  <= 10 pages, async jobs, 23 languages. Dashboard itself is login-gated (couldn't view). Not integrated yet.
- Chat models: `sarvam-30b`, `sarvam-105b` (`sarvam-m` deprecated). Docs MCP: `https://docs.sarvam.ai/_mcp/server`.
- Voice Agents MCP: `https://mcp.sarvam.ai/voice-agents` (create/edit agents, variables, telephony, campaigns,
  evals, transcripts; OAuth via Sarvam SSO, 24h tokens).

## Current state / blockers
- `.env` now holds SARVAM_API_KEY, SARVAM_APPS_API_KEY, SARVAM_ORG_ID, SARVAM_WORKSPACE_ID and SARVAM_AGENT_ID
  (see `.env.example`), so "Fetch latest calls" is ready. Still unset: WEBHOOK_URL (public tunnel +
  `/sarvam/webhook`) and WEBHOOK_TOKEN for push delivery; for placing calls by API also SARVAM_AGENT_VERSION,
  SARVAM_CONNECTION_ID, SARVAM_AGENT_PHONE.
- MCP `sarvam-voice-agents` was added with `claude mcp add --transport http ...` but status was
  "Needs authentication". User must run `/mcp` -> authenticate, then restart the session.
- A stale-Streamlit ImportError (`env_value`) was fixed by restarting Streamlit; code was fine.
- The pasted API key was shared in chat once: rotate after the hackathon.

## Next steps (agreed order)
1. With the MCP connected: read-only first (list org/workspace/connections), fill `.env`; then, with user approval
   for each change, create the agent from `docs/sarvam_agent_prompt.md`; run a test scenario before any real call.
2. First live call to the user's own number; verify X-API-Key acceptance and that `agent_variables` strings work;
   check whether the dashboard wants `{{var}}` or `@` variable syntax.
3. Then (user said "later"): improve extraction/accuracy: Document AI extract adapter for raw images/PDFs as a
   second source in fusion; LLM (sarvam-30b/105b) category rerank constrained to the 696 taxonomy, backtested;
   LLM fallback for unparseable voice replies; regional-script addresses.
4. Quick wins from the error analysis (city aliases, pincode sanity, name normalisation); see README roadmap.

## Gotchas
- Never place a real call without explicit user go-ahead; consent checkbox exists in the UI.
- Do not print or commit secrets. Confirm before creating/changing anything in the Sarvam workspace.
- Dataset has document paths only, no images, so Sarvam extraction cannot be backtested at scale.
