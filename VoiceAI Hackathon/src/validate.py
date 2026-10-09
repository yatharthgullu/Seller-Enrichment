"""
Backtest the fused profiles against IndiaMART's verified answer key
(so_sellers.csv / so_seller_categories.csv). This module is the only place
in the codebase allowed to read those ground-truth columns -- fusion.py and
taxonomy.py never see them, so these numbers are a genuine out-of-sample
check, not a circular one.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from src.gstin_rules import sixth_char_matches

NAME_MATCH_THRESHOLD = 80


def _has_value(x) -> bool:
    if x is None:
        return False
    if isinstance(x, float):
        return x == x  # filters NaN
    return str(x).strip() != "" and str(x).strip().lower() != "nan"


def _norm(s) -> str:
    return str(s).strip().lower() if _has_value(s) else ""


def score_seller(profile: dict, seller_row: dict, true_categories: list[dict]) -> dict:
    """Compare one fused profile against that seller's ground-truth row.
    Returns a dict of per-field booleans/scores (None = not comparable)."""
    result: dict = {"seller_id": profile["seller_id"]}

    # --- company name -------------------------------------------------
    pred_name = profile["company_name"]["value"]
    true_name = seller_row.get("company_name")
    if pred_name and _has_value(true_name):
        sim = fuzz.token_sort_ratio(_norm(pred_name), _norm(true_name))
        result["company_name_similarity"] = round(sim, 1)
        result["company_name_match"] = sim >= NAME_MATCH_THRESHOLD
    else:
        result["company_name_similarity"] = None
        result["company_name_match"] = None

    # --- GSTIN (validated via the privacy-safe 6th-char field only) ---
    pred_gstin = profile["gstin"]["value"]
    true_6th = seller_row.get("gstin_num_6th_char")
    match = sixth_char_matches(pred_gstin, true_6th)
    result["gstin_extracted"] = bool(pred_gstin)
    result["gstin_6th_char_match"] = match

    # --- legal status ---------------------------------------------------
    pred_legal = profile["legal_status"]["value"]
    true_legal = seller_row.get("legal_status")
    if pred_legal and _has_value(true_legal):
        result["legal_status_match"] = _norm(pred_legal) == _norm(true_legal)
    else:
        result["legal_status_match"] = None

    # --- location ---------------------------------------------------------
    pred_city = profile["address"]["city"]["value"]
    true_city = seller_row.get("city_name")
    if pred_city and _has_value(true_city):
        result["city_match"] = _norm(pred_city) == _norm(true_city)
    else:
        result["city_match"] = None

    pred_state = profile["address"]["state"]["value"]
    true_state = seller_row.get("state_name")
    if pred_state and _has_value(true_state):
        result["state_match"] = _norm(pred_state) == _norm(true_state)
    else:
        result["state_match"] = None

    pred_pin = profile["address"]["pincode"]["value"]
    true_pin = seller_row.get("pincode")
    if pred_pin and _has_value(true_pin):
        result["pincode_match"] = str(pred_pin).strip() == str(int(true_pin)).strip()
    else:
        result["pincode_match"] = None

    # --- field coverage (did we produce a confident value at all?) -----
    coverage_fields = {
        "company_name": profile["company_name"],
        "gstin": profile["gstin"],
        "legal_status": profile["legal_status"],
        "city": profile["address"]["city"],
        "state": profile["address"]["state"],
        "pincode": profile["address"]["pincode"],
    }
    result["fields_populated"] = sum(1 for f in coverage_fields.values() if f["value"])
    result["fields_high_confidence"] = sum(
        1 for f in coverage_fields.values() if f["value"] and f["confidence"] >= 0.7
    )
    result["fields_total"] = len(coverage_fields)

    return result


def score_categories(predicted: list[dict], true_categories: list[dict]) -> dict:
    """Precision of predicted top-k categories against the seller's real
    category list, and specifically against their real top-5 / A-rank set."""
    pred_names = {p["category_name"] for p in predicted}
    if not pred_names:
        return {
            "category_predictions": 0,
            "category_hit_rate": None,
            "top5_precision": None,
        }

    true_all = {c["category_name"] for c in true_categories}
    true_top5 = {c["category_name"] for c in true_categories if c.get("is_top5_category")}

    hits_all = len(pred_names & true_all)
    out = {
        "category_predictions": len(pred_names),
        "category_hit_rate": round(hits_all / len(pred_names), 3),
    }
    if true_top5:
        hits_top5 = len(pred_names & true_top5)
        out["top5_precision"] = round(hits_top5 / len(pred_names), 3)
        out["top5_recall"] = round(hits_top5 / len(true_top5), 3)
    else:
        out["top5_precision"] = None
        out["top5_recall"] = None
    return out


def aggregate(per_seller_scores: list[dict]) -> dict:
    """Roll per-seller score dicts up into dataset-level summary metrics."""

    def rate(field):
        vals = [r[field] for r in per_seller_scores if r.get(field) is not None]
        return {"n": len(vals), "rate": round(sum(vals) / len(vals), 3) if vals else None}

    def avg(field):
        vals = [r[field] for r in per_seller_scores if r.get(field) is not None]
        return {"n": len(vals), "avg": round(sum(vals) / len(vals), 3) if vals else None}

    total = len(per_seller_scores)
    avg_fields_populated = sum(r["fields_populated"] for r in per_seller_scores) / total if total else 0
    avg_fields_total = per_seller_scores[0]["fields_total"] if per_seller_scores else 0

    return {
        "sellers_scored": total,
        "company_name_match_rate": rate("company_name_match"),
        "company_name_similarity_avg": avg("company_name_similarity"),
        "gstin_6th_char_match_rate": rate("gstin_6th_char_match"),
        "legal_status_match_rate": rate("legal_status_match"),
        "city_match_rate": rate("city_match"),
        "state_match_rate": rate("state_match"),
        "pincode_match_rate": rate("pincode_match"),
        "avg_fields_populated": round(avg_fields_populated, 2),
        "fields_total_per_seller": avg_fields_total,
        "field_coverage_rate": round(avg_fields_populated / avg_fields_total, 3) if avg_fields_total else None,
        "category_hit_rate": avg("category_hit_rate"),
        "category_top5_precision": avg("top5_precision"),
    }
