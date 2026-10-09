"""Flatten fused seller profiles into a single downloadable table.

One row per seller, with each field's value AND its confidence score as
separate columns -- this is what a reviewer / downstream system actually
needs: not just "what did the pipeline guess" but "how much should I trust
it", side by side, so a confidence-threshold cutoff can be applied later
without re-running anything.
"""
from __future__ import annotations

import pandas as pd


def flatten_profile(seller_id: str, entry: dict) -> dict:
    p = entry["profile"]
    cats = entry.get("category_suggestions") or []
    top_cat = cats[0] if cats else {}

    return {
        "seller_id": seller_id,
        "doc_count": p["doc_count"],
        "doc_types_seen": "|".join(p["doc_types_seen"]),

        "company_name": p["company_name"]["value"],
        "company_name_confidence": p["company_name"].get("calibrated_confidence", p["company_name"]["confidence"]),
        "company_name_sources": "|".join(p["company_name"]["sources"]),

        "gstin": p["gstin"]["value"],
        "gstin_confidence": p["gstin"]["confidence"],  # not independently validated, raw only

        "legal_status": p["legal_status"]["value"],
        "legal_status_confidence": p["legal_status"].get("calibrated_confidence", p["legal_status"]["confidence"]),

        "city": p["address"]["city"]["value"],
        "city_confidence": p["address"]["city"].get("calibrated_confidence", p["address"]["city"]["confidence"]),

        "state": p["address"]["state"]["value"],
        "state_confidence": p["address"]["state"].get("calibrated_confidence", p["address"]["state"]["confidence"]),

        "pincode": p["address"]["pincode"]["value"],
        "pincode_confidence": p["address"]["pincode"].get("calibrated_confidence", p["address"]["pincode"]["confidence"]),

        "top_category": top_cat.get("category_name"),
        "top_category_group": top_cat.get("group_name"),
        "top_category_confidence": top_cat.get("confidence"),

        "risk_flags": "|".join(p.get("risk_flags", [])),
    }


def build_export_dataframe(enriched: dict) -> pd.DataFrame:
    rows = [flatten_profile(sid, entry) for sid, entry in enriched.items()]
    return pd.DataFrame(rows)
