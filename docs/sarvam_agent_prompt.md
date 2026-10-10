# Sarvam agent contract: seller profile confirmation call

Agent: **IndiaMART Seller Profile Verification** (`Conversatio-781986af-18df`). The prompt
lives in the Sarvam dashboard. These variable names are a contract with the code
(`src/outbound.py`, `src/sarvam_calls.py`), so keep them exactly. Field keys are
`company_name, gstin, legal_status, city, state, pincode`.

## Input variables (you fill them when you start the call)

| Variable | Example | Meaning |
|---|---|---|
| `glid` | 12345678 | the seller; echoed back so the result is matched to them |
| `business_name` | SHARMA SURGICAL | business being called about |
| `fields_to_confirm` | gstin, city, pincode | fields we have a value for; read back |
| `fields_to_collect` | state | fields we have no value for; ask the seller |
| `<field>_current` | `city_current` = Bhiwani | value on file for each field (blank if none) |

## Output variables (the agent sets them after the call)

| Variable | Format |
|---|---|
| `confirmed_fields` | comma list, e.g. `gstin, city`, or `none` |
| `updated_fields` | corrections, `city: Pune; pincode: 411001`, or `none` |
| `collected_values` | newly given values, `state: Maharashtra`, or `none` |
| `call_disposition` | profile_confirmed / corrections_provided / partial_completion / callback_requested / declined / wrong_person / unclear |
| `call_summary` | 1-2 line summary |

A field in the field table is: **corrected** if in `updated_fields`, **collected** if in
`collected_values`, **confirmed** if in `confirmed_fields`, otherwise **not confirmed**;
fields not listed in `fields_to_confirm`/`fields_to_collect` are **not asked**.

## Running a call

1. Open the seller in the app, expand "Confirm by phone call", copy the variables (or
   download the cohort CSV: map `phone_number` to the phone and every other column, including
   `glid`, to the agent variable of the same name. Do not rely on `user_identifier`: the
   analytics API returns it as a SHA-256 hash).
2. Start the call in the Sarvam dashboard. Variables must exist on the **committed**
   agent version, so commit after editing the agent.
3. Results arrive by webhook or on **Fetch latest calls**:
   - webhook: `python scripts/webhook_server.py`, tunnel port 8787 (ngrok/cloudflared),
     set the campaign webhook to `<tunnel>/sarvam/webhook?token=<WEBHOOK_TOKEN>`.
     Webhooks are a campaign setting; single test calls may not send one.
   - fetch: calls Sarvam's analytics `attempts` API for this agent.
4. Check the table, then **Apply**. Values are re-validated (GSTIN check digit, pincode
   shape, city/state list) before they overwrite a field.

## `.env`

```
SARVAM_APPS_API_KEY=...   # Voice Agents key (Settings -> API Key). NOT the speech key
SARVAM_ORG_ID=...
SARVAM_WORKSPACE_ID=...
SARVAM_AGENT_ID=...
SARVAM_API_KEY=...        # speech/text key; only for Hindi transliteration
WEBHOOK_URL=...           # optional, for the webhook path
WEBHOOK_TOKEN=...
# SARVAM_AGENT_VERSION, SARVAM_CONNECTION_ID, SARVAM_AGENT_PHONE: only if placing calls from code
```
