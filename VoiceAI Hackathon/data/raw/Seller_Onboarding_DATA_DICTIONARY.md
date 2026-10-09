# 06 · Seller Onboarding (Seller Enrichment) – Dataset

**What it's for:** building a system that takes a new seller's raw inputs (photos, documents, invoices, sign boards, voice / chat), turns them into an IndiaMART profile and catalogue, and verifies the documents.
**Sample:** 5,000 sellers whose profiles are already verified, so the files can be used as the answer key.
- 3,000 **Video KYC sellers** (`cohort = video_kyc`). They uploaded real documents and photos that IndiaMART accepted or rejected, and each has field-level pass / fail checks.
- 2,000 **verified paid sellers** (TrustSEAL 1,464, STAR 347, LEADER 189). All are GST-verified and mobile-verified, and all have a PAN on file.

**Join key:** `fk_glusr_usr_id` (seller GLID) in every seller file.
**Sources:** IndiaMART warehouse, pg-main and ClickHouse via Redash, pulled 8 Oct 2026. Only data readable through Redash is included.
**Cleaning:**
- Columns empty for all records, or with one value for everyone, were dropped.
- Phone numbers, emails and Aadhaar numbers were removed from the AI-extracted document fields.
- Bank account numbers are masked except their last 4 digits.

## Files

| File | One row per | Rows | Sellers |
|---|---|---|---|
| **Seller answer key** | | | |
| `so_sellers.csv` | seller: verified profile | 5,000 | 5,000 |
| `so_seller_locations.csv` | seller location (sellers can have several) | 9,497 | 4,808 |
| `so_seller_categories.csv` | category the seller is listed in | 294,245 | 4,893 |
| `so_products_part1.csv`, `so_products_part2.csv` | product listing (latest 50 per seller; split by seller) | 208,310 | 4,949 |
| `so_catalog_health.csv` | seller: catalogue gaps (missing images, prices, specs…) | 4,910 | 4,910 |
| **Raw inputs and verification labels (Video KYC sellers)** | | | |
| `so_kyc_documents.csv` | uploaded document or photo, with accepted / rejected label | 32,724 | 3,000 |
| `so_kyc_field_checks.csv` | profile field checked during KYC, pass / fail | 39,461 | 3,000 |
| `so_kyc_sessions.csv` | Video KYC session | 3,132 | 3,000 |
| **Reference** | | | |
| `ref_category_taxonomy.csv` | live product category (MCAT) with its full tree | 106,619 | – |
| `ref_category_specs.csv` | spec field a category uses, with common options | 943,925 | – |
| `ref_legal_status.csv`, `ref_turnover_slabs.csv`, `ref_states.csv`, `ref_cities.csv` | lookup values for profile fields | small | – |
| `ref_document_types.csv`, `ref_kyc_fields.csv` | names of KYC document types and checked fields | small | – |

---

## so_sellers.csv: the verified profile (answer key)
- **Identity:** `company_name`, `customer_type` (TrustSEAL, STAR…), `cohort`, `member_since`, `listing_status`, `approval_status`
- **Location:** `city_name`, `district_name`, `state_name`, `locality`, `pincode`, `latitude`, `longitude`
- **Business:**
  - `legal_status` (text, from `legal_status_id`)
  - `year_established`
  - `employees_id`
  - `turnover_declared` (text, from `turnover_id`)
  - `annual_turnover_slab`
  - `business_nature_id(s)`
- **Person / role:** `contact_designation` (e.g. Proprietor, Director). Names are not in Redash; only `is_lname_available` shows whether a last name exists.
- **GST (government record):**
  - `gst_partner_names` (owners / partners)
  - `gst_legal_status`
  - `gst_nature_of_business` (+ `_secondary`)
  - `gst_annual_turnover`
  - `gst_registration_year`
  - `gst_verification_date`
- **Verification flags** (1 = present / verified): mobile, email, alternate mobile, GST, business type, visiting card, bank name / IFSC / account, profile image, website
- **Links:** `paidshowroom_url` / `freeshowroom_url` (the seller's IndiaMART catalogue page), `logo_url`

All 5,000 sellers are GST-verified and have a PAN, so those two flags were dropped as constant.

## so_seller_locations.csv
Each seller's business locations, ranked: `cluster_rank` (1 = main), `city`, `state`, `pincode`, `address_source` (OLA / MAPMYINDIA geocoding), `latlong_source`. Street address is not in Redash.

## so_seller_categories.csv
Every category the seller is listed in, with the tree: `mcat_name` → `parent_mcat_name` → `category_name` → `group_name`. Flags: `is_top5_category`, `is_a_rank` (a core category), `is_primary_mapping`. Sellers have a median of 31 categories.

## so_products.csv: the finished catalogue
For each seller's latest 50 products:
- `product_name`
- `mcat_id` / `mcat_name` (the category it's mapped to)
- `price`, `price_unit`, `moq_unit`
- `description` (HTML converted to plain text)
- `product_specifications` ("Brand : X | Material : Y | …")
- `image_url` (13% filled)
- `approval_status`

## so_catalog_health.csv
Counts of what's wrong or missing in each seller's catalogue:
- products without an image, price, specs, description or category
- name-only products
- out-of-stock products
- low quality-score products
- products in negative categories

Use it as the "before" state an onboarding system should fix.

## so_kyc_documents.csv: raw inputs with labels (most important file)
One row per document or photo uploaded during Video KYC.
- `document_type`: selfie, KYC video, sign board, shop board, office setup, inventory, product photo, product invoice, invoice header, invoice details, cancelled cheque, Udyam certificate, utility bill, or other.
- `verification_status`: accepted 24,792 / rejected 7,146 / pending 786.
- `uploaded_on`, `verified_on`, `verification_src_id` (507 or 506: the verification route; meaning to be confirmed).
- `document_path`: storage path of the file (e.g. `WEBERP/IILAttachment/...jpeg`). The files themselves need a storage base URL and access from tech.
- `original_file_path`: the uploaded file's original path (often a WhatsApp image).
- `llm_extraction`: on 13,039 documents, IndiaMART's own AI reading of the document, as JSON. Contents vary by document type:
  - Invoices: GST, company name, address, line-item products with unit and price, total amount, buyer details.
  - Sign boards: company name, address, website.
  - Work setup photos: workspace type, confidence, reasoning.
  - Some documents also carry audit verdicts and HSN mapping.
  - This is a ready baseline to beat, or to train against.
- `image_check_metadata`: face-check results for selfies (face detected, eyes open, confidence).

Accept / reject counts by type:

| Document | Accepted | Rejected |
|---|---|---|
| Product invoice | 1,309 | 1,698 |
| Invoice header / details | 1,698 / 1,619 | 948 / 995 |
| Product photo | 2,326 | 655 |
| Inventory | 2,411 | 579 |
| Shop board / sign board | 1,095 / 1,941 | 559 / 326 |
| Office setup | 2,568 | 419 |
| Cancelled cheque | 833 | 224 |
| Udyam certificate | 410 | 104 |
| Selfie / video | 2,976 / 2,793 | 26 / 198 |

## so_kyc_field_checks.csv
Pass / fail for each profile field checked against the documents.

| Field | Passed | Failed |
|---|---|---|
| Company name | 4,443 | 497 |
| GST | 3,078 | 1,547 |
| Trade name | 540 | 58 |
| Work setup | 2,026 | 355 |
| Products matched | 1,421 | 792 |
| Inventory matched | 1,358 | 832 |
| Udyam | 217 | 134 |
| Liveness | 2,378 | 0 |

Mobile and email checks are also included. Only the result is given, not the number or address.

## so_kyc_sessions.csv
One row per Video KYC session:
- `workorder_id`
- `created_on`
- `profile_created_on` / `profile_completed_on`
- `video_kyc_start_time` / `video_kyc_end_time`
- `gps_latitude` / `gps_longitude`: where the KYC was done.
- `gst_addr_lat` / `gst_addr_lng`: the GST address location. Comparing the two is a location check.

## ref_category_taxonomy.csv
The live IndiaMART category tree: 58 groups → 696 categories → 9,193 parent MCATs → 106,619 MCATs. It also carries the flags that change what a listing needs:
- `is_product`
- `no_price`, `no_unit`
- `quantity_enabled`
- `spec_count`
- `template_name`
- `location_pref`
- `image_url`

## ref_category_specs.csv
For 49,838 categories, the spec fields their products use:
- `spec_name`
- `spec_type`: R, K or C; meaning to be confirmed with the catalogue team (likely single-choice, keyword or custom).
- `priority`: lower = more important.
- `products_using`: how many products fill it.
- `top_options`: up to 15 most common values, `|`-separated.

Seller-created custom specs (spec id -1) were removed.

---

## Not included (not accessible through Redash)
- **Street address, contact person names, phone numbers, emails:** removed from all Redash copies.
- **The document image and video files:** only storage paths are available.
- **Profile field rules** (formats, lengths, mandatory fields): need the seller-panel / catalogue team.
- **Full seller, contact, bank and company-registration tables** in pg-main (`public` schema): permission denied.
- **Multilingual catalogue text:** product names carry a language ID, but the mapping isn't documented, so it wasn't included.
