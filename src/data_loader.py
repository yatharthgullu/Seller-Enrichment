"""Load and lightly normalize the raw hackathon CSVs."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import pandas as pd

from src import config


def _read_csv(path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False, **kwargs)


# --- answer-key / ground-truth tables ---------------------------------------

def load_sellers() -> pd.DataFrame:
    df = _read_csv(config.F_SELLERS)
    df["fk_glusr_usr_id"] = df["fk_glusr_usr_id"].astype(str)
    return df


def load_locations() -> pd.DataFrame:
    df = _read_csv(config.F_LOCATIONS)
    df["fk_glusr_usr_id"] = df["fk_glusr_usr_id"].astype(str)
    return df


def load_categories() -> pd.DataFrame:
    df = _read_csv(config.F_CATEGORIES)
    df["fk_glusr_usr_id"] = df["fk_glusr_usr_id"].astype(str)
    return df


def load_catalog_health() -> pd.DataFrame:
    df = _read_csv(config.F_CATALOG_HEALTH)
    df["fk_glusr_usr_id"] = df["fk_glusr_usr_id"].astype(str)
    return df


# --- raw KYC documents (the "non-IM data" inputs) ---------------------------

def load_kyc_documents() -> pd.DataFrame:
    df = _read_csv(config.F_KYC_DOCUMENTS)
    df["fk_glusr_usr_id"] = df["fk_glusr_usr_id"].astype(str)
    return df


def _safe_json(raw: Any) -> dict | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def group_extracted_documents_by_seller(
    docs_df: pd.DataFrame,
) -> dict[str, list[dict]]:
    """Return {seller_id: [{"doc_type": ..., "extraction": {...}, "status": ...}, ...]}

    Only rows whose document_type is one of config.EXTRACTABLE_DOC_TYPES and
    whose llm_extraction parses as JSON are kept.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    subset = docs_df[docs_df["document_type"].isin(config.EXTRACTABLE_DOC_TYPES)]
    for row in subset.itertuples(index=False):
        extraction = _safe_json(getattr(row, "llm_extraction"))
        if extraction is None:
            continue
        out[getattr(row, "fk_glusr_usr_id")].append(
            {
                "doc_type": getattr(row, "document_type"),
                "extraction": extraction,
                "verification_status": getattr(row, "verification_status"),
                "uploaded_on": getattr(row, "uploaded_on"),
            }
        )
    return dict(out)


# --- reference / taxonomy tables --------------------------------------------

def load_taxonomy() -> pd.DataFrame:
    return _read_csv(config.F_REF_TAXONOMY)


def load_cities() -> pd.DataFrame:
    return _read_csv(config.F_REF_CITIES)


def load_states() -> pd.DataFrame:
    return _read_csv(config.F_REF_STATES)


def load_legal_status() -> pd.DataFrame:
    return _read_csv(config.F_REF_LEGAL_STATUS)


def load_turnover_slabs() -> pd.DataFrame:
    return _read_csv(config.F_REF_TURNOVER)
