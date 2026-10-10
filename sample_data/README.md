# Sample data: what we pass in, and 10 test sellers

This folder is a self-contained test pack for the Seller Enrichment app. All names, GLIDs (`9001000xx`),
PANs and addresses are **fictional**. GSTINs are well-formed with a correct check digit, so the validator
treats them like real ones. No personal data is included.

| File | What it is |
|---|---|
| `sample_10_sellers.csv` | **The upload file.** 24 documents for 10 sellers, one row per document. |
| `sample_10_sellers.json` | The same data in the JSON layout the app also accepts. |
| `sample_10_sellers_scenarios.csv` | What each seller is meant to demonstrate, and what the app should say. |
| `README.md` | This guide. |

## 1. What goes in: one row per document

The input is what an upstream OCR / LLM step already extracted from a seller's KYC documents. The app does
**not** read images; it fuses the extracted fields across documents.

| Column | Meaning |
|---|---|
| `fk_glusr_usr_id` | The seller's GLID. All rows with the same GLID are fused into one profile. (`seller_id` also works.) |
| `document_type` | Exactly one of: `Product Invoice`, `Sign Board`, `Udhyam Certificate`, `CANCELLED CHEQUE`. Case-sensitive. Other types are skipped and counted in the upload summary. (`doc_type` also works.) |
| `llm_extraction` | The extracted fields of that one document, as a JSON object. (`extraction` also works.) |

### What is read from each document type

| Document type | Keys read from `llm_extraction` | Feeds |
|---|---|---|
| `Product Invoice` | `CompanyName[]`, `GST[]`, `Address[]`, `Products[]` (`name`, `unit`, `price_per_unit`) | company name, GSTIN, city, state, pincode, products |
| `Sign Board` | `CompanyName[]`, `GST[]`, `Address[]` | company name, GSTIN, city, state, pincode |
| `Udhyam Certificate` | `udyam_data.parsed_names.trade_name`, `udyam_data.official_address.{city,state,pincode,...}`, `udyam_data.enterprise_type`, `udyam_data.nic_codes[]`, `gstin_verification.{provided_gstin,state_code_match}` | company name, GSTIN, address, enterprise type, risk flag |
| `CANCELLED CHEQUE` | `accholder_name.value`, `bank_address.value` | company name (weak), locality (very weak) |

Any other keys are ignored. Missing keys are fine: a field nothing supplies simply comes back as "fill in".

### Source reliability and what it means

Each source has a weight (Udyam certificate highest, cancelled cheque lowest). A value that several documents
agree on scores higher; a disagreement lowers the score. **Legal status is not read from any document: it is
derived from the GSTIN's PAN entity character** (P = proprietor, F = partnership, C = company, H = HUF), so it is
only as certain as the GSTIN. If the GSTIN appears on a single document, legal status asks for a confirmation.

### Accepted JSON layouts (same content)

```json
{ "900100001": [ { "doc_type": "Sign Board", "extraction": { "CompanyName": ["..."] } } ] }
```

or `{ "seller_id": "900100001", "documents": [ ... ] }`, or a flat list of documents that each carry a `seller_id`.

### Example row (CSV)

```
fk_glusr_usr_id,document_type,llm_extraction
900100005,Product Invoice,"{""CompanyName"":[""VELAN ELECTRICALS""],""GST"":[""33DNRPV8842H1Z6""],""Address"":[""No. 7, Gandhi Road""],...}"
```

## 2. What comes out

For every seller and each of six fields (company name, GSTIN, legal status, city, state, pincode): a value, a
calibrated confidence, the reasons, and a bucket:

| Bucket | Meaning | What happens next |
|---|---|---|
| **Auto-filled** | High confidence | Nothing. |
| **Please confirm** / **Review** | A value exists but is uncertain or contested | The voice agent reads it back (`fields_to_confirm`). |
| **Fill in** | No document gave it | The voice agent asks for it (`fields_to_collect`). |

## 3. The 10 sellers


| GLID | Scenario | Documents | App will confirm | App will collect | What to look for |
|---|---|---|---|---|---|
| 900100001 | **Complete profile, nothing to do** | Udhyam Certificate, Product Invoice, Sign Board, CANCELLED CHEQUE | - | - | Four documents agree on every field. All six fields are auto-filled; no call is needed. |
| 900100002 | **Complete profile (private limited company)** | Udhyam Certificate, Product Invoice, Sign Board | - | - | Udyam, invoice and sign board agree. Legal status is derived from the GSTIN (entity char 'C'). |
| 900100003 | **2 to confirm, 0 to collect** | Product Invoice, Sign Board, CANCELLED CHEQUE | company_name, pincode | - | The three documents spell the business differently and only the sign board gives a pincode (one weak source). The agent reads those two values back. |
| 900100004 | **2 to confirm, 1 to collect** | Product Invoice, CANCELLED CHEQUE | company_name, legal_status | pincode | No document carries a pincode (collect). The GSTIN appears on one document only, so the legal status derived from it is a confirm, and the company name is only half-agreed (confirm). |
| 900100005 | **1 to confirm, 2 to collect** | Product Invoice, Sign Board | legal_status | city, pincode | The invoice has a name and GSTIN but an address with no city or pincode, so city and pincode are collected. Legal status is derived from a GSTIN seen once, so it is confirmed. |
| 900100006 | **Sparse: cheque only** | CANCELLED CHEQUE | company_name, city, state | gstin, legal_status, pincode | Only a cancelled cheque was uploaded. Its account-holder name and bank address are weak signals (company, city and state are confirmed); GSTIN, legal status and pincode are missing and collected. |
| 900100007 | **GSTIN misread by OCR** | Product Invoice, Sign Board | gstin, legal_status | - | The invoice's GSTIN fails its check digit; the sign board's reading passes. The app suggests the valid one and lowers confidence on legal status, which is derived from it. |
| 900100008 | **Conflicting company names** | Product Invoice, Sign Board, CANCELLED CHEQUE | company_name | - | Invoice and sign board name different businesses. The app shows both and asks which is right. |
| 900100009 | **Udyam and GSTIN disagree on state** | Udhyam Certificate, Product Invoice | city, state, pincode | - | The Udyam certificate puts the unit in Karnataka but the GSTIN is a Telangana one, so the state is flagged and a risk flag is raised. |
| 900100010 | **Partnership firm, 1 to collect** | Product Invoice, Sign Board | - | pincode | Two documents agree on name, GSTIN and city, but neither gives a pincode, so only that is collected. |

## 4. Testing the whole flow

1. Start the app, open **Enrich sellers**, then **Choose files** and pick `sample_10_sellers.csv`
   (or press **Try the 10-seller test set**).
2. The queue shows 10 sellers: 2 ready, 8 needing a person. Open each one and compare it with the table above.
3. Resolve fields by hand (**Confirm**, **Use "..."**, **Edit**) and watch the counts and the "settled fields" bar update.
4. Open **Phone verification** for a seller (try `900100005`, `900100004` or `900100003`). Step 1 shows exactly what the
   agent will confirm and collect. Copy the variables, start the call in the Sarvam dashboard with the **GLID in the
   `glid` variable**, answer as the seller, then press **Fetch latest calls**.
5. Review the field table (on file, outcome, new value) and **Apply** the validated values to the profile.

### What the voice agent is given for a seller

`glid`, `business_name`, `fields_to_confirm` (comma list), `fields_to_collect` (comma list) and `<field>_current`
for every field that has a value (`company_name_current`, `gstin_current`, `legal_status_current`, `city_current`,
`state_current`, `pincode_current`). It returns `confirmed_fields`, `updated_fields` (`city: Pune; pincode: 411001`),
`collected_values`, `call_disposition` and `call_summary`, which the app maps back onto the same six fields by GLID.

Values the agent reports are re-validated (GSTIN check digit, pincode shape, city/state list) before they can
overwrite a field.

*Regenerate this pack with `python scripts/make_sample_dataset.py --check`. The check runs every seller through the
real engine and fails if a scenario no longer behaves as described.*
