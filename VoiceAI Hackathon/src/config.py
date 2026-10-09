"""Paths and shared constants for the Seller Enrichment pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)

# --- raw files -------------------------------------------------------------
F_SELLERS = DATA_RAW / "so_sellers.csv"
F_LOCATIONS = DATA_RAW / "so_seller_locations.csv"
F_CATEGORIES = DATA_RAW / "so_seller_categories.csv"
F_CATALOG_HEALTH = DATA_RAW / "so_catalog_health.csv"
F_KYC_DOCUMENTS = DATA_RAW / "so_kyc_documents.csv"
F_KYC_FIELD_CHECKS = DATA_RAW / "so_kyc_field_checks.csv"
F_KYC_SESSIONS = DATA_RAW / "so_kyc_sessions.csv"
F_PRODUCTS_1 = DATA_RAW / "so_products_part1.csv"
F_PRODUCTS_2 = DATA_RAW / "so_products_part2.csv"

F_REF_TAXONOMY = DATA_RAW / "ref_category_taxonomy.csv"
F_REF_CATEGORY_SPECS = DATA_RAW / "ref_category_specs.csv"
F_REF_CITIES = DATA_RAW / "ref_cities.csv"
F_REF_STATES = DATA_RAW / "ref_states.csv"
F_REF_LEGAL_STATUS = DATA_RAW / "ref_legal_status.csv"
F_REF_TURNOVER = DATA_RAW / "ref_turnover_slabs.csv"
F_REF_DOC_TYPES = DATA_RAW / "ref_document_types.csv"
F_REF_KYC_FIELDS = DATA_RAW / "ref_kyc_fields.csv"

# --- document types that carry usable llm_extraction JSON ------------------
# (measured directly against the dataset: these are the only types where
# `llm_extraction` is populated for a meaningful share of rows)
EXTRACTABLE_DOC_TYPES = {
    "Product Invoice",
    "Sign Board",
    "Udhyam Certificate",
    "CANCELLED CHEQUE",
}

# Source reliability weights used by the fusion engine (0-1).
# Government / registry sources outrank OCR'd business documents.
SOURCE_WEIGHT = {
    "Udhyam Certificate": 0.95,   # government registry
    "Product Invoice": 0.65,      # seller's own commercial doc, high detail
    "Sign Board": 0.55,           # photographed signage, short text
    "CANCELLED CHEQUE": 0.45,     # bank record, name often = account title not trade name
}

CONFIDENCE_HIGH = 0.8
CONFIDENCE_MED = 0.5
