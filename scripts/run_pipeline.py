"""
End-to-end runner: raw KYC documents -> fused, confidence-scored seller
profiles -> taxonomy-mapped categories -> backtest against the verified
answer key -> outputs/*.json for the Streamlit app and the submission
write-up.

Usage:
    python scripts/run_pipeline.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import calibration as calibrate
from src import config, data_loader as dl, fusion, validate
from src.address_parser import CityMatcher
from src.taxonomy import CategoryMapper


def log(msg: str) -> None:
    print(f"[run_pipeline] {msg}", flush=True)


def main(limit: int | None = None) -> None:
    t0 = time.time()

    log("loading raw tables...")
    sellers_df = dl.load_sellers()
    categories_df = dl.load_categories()
    docs_df = dl.load_kyc_documents()
    cities_df = dl.load_cities()
    states_df = dl.load_states()
    taxonomy_df = dl.load_taxonomy()
    catalog_health_df = dl.load_catalog_health()

    sellers_by_id = sellers_df.set_index("fk_glusr_usr_id").to_dict("index")
    catalog_health_by_id = catalog_health_df.set_index("fk_glusr_usr_id").to_dict("index")

    cats_by_seller: dict[str, list[dict]] = {}
    for row in categories_df.itertuples(index=False):
        cats_by_seller.setdefault(row.fk_glusr_usr_id, []).append(
            {
                "category_name": row.category_name,
                "group_name": row.group_name,
                "mcat_name": row.mcat_name,
                "is_top5_category": bool(row.is_top5_category),
                "is_a_rank": bool(row.is_a_rank),
            }
        )

    log("grouping extractable KYC documents by seller...")
    grouped_docs = dl.group_extracted_documents_by_seller(docs_df)
    seller_ids = list(grouped_docs.keys())
    if limit:
        seller_ids = seller_ids[:limit]
    log(f"{len(seller_ids)} sellers have >=1 extractable document")

    log("building city/state gazetteer matcher...")
    city_matcher = CityMatcher(cities_df, states_df)

    log("building category taxonomy mapper...")
    category_mapper = CategoryMapper(taxonomy_df)

    log("fusing profiles...")
    profiles: dict[str, dict] = {}
    category_suggestions: dict[str, list[dict]] = {}
    for i, sid in enumerate(seller_ids, 1):
        profile = fusion.build_seller_profile(sid, grouped_docs[sid], city_matcher)
        profiles[sid] = profile
        category_suggestions[sid] = category_mapper.suggest_for_profile(profile, top_k=5)
        if i % 500 == 0:
            log(f"  fused {i}/{len(seller_ids)}")

    log("scoring against the verified answer key...")
    per_seller_scores = []
    category_scores = []
    for sid in seller_ids:
        seller_row = sellers_by_id.get(sid)
        if not seller_row:
            continue  # seller not in the verified set (shouldn't happen, but be safe)
        true_cats = cats_by_seller.get(sid, [])
        s = validate.score_seller(profiles[sid], seller_row, true_cats)
        per_seller_scores.append(s)
        cs = validate.score_categories(category_suggestions[sid], true_cats)
        cs["seller_id"] = sid
        category_scores.append(cs)
        s["category_hit_rate"] = cs["category_hit_rate"]
        s["top5_precision"] = cs["top5_precision"]

    summary = validate.aggregate(per_seller_scores)

    # --- confidence calibration ---------------------------------------
    # The raw fusion confidence ranks fields correctly (higher = more
    # accurate) but is conservative on an absolute scale -- fit a mapping
    # from raw confidence -> empirical accuracy per field type, using
    # exactly the (confidence, correct?) pairs the backtest above just
    # produced, then attach a `calibrated_confidence` to every scored field.
    FIELD_SPECS = [
        ("company_name", lambda p: p["company_name"], "company_name_match"),
        ("legal_status", lambda p: p["legal_status"], "legal_status_match"),
        ("city", lambda p: p["address"]["city"], "city_match"),
        ("state", lambda p: p["address"]["state"], "state_match"),
        ("pincode", lambda p: p["address"]["pincode"], "pincode_match"),
    ]
    scores_by_sid = {s["seller_id"]: s for s in per_seller_scores}

    pairs = []
    for field_name, getter, match_key in FIELD_SPECS:
        for sid in seller_ids:
            s = scores_by_sid.get(sid)
            if not s or s.get(match_key) is None:
                continue
            field = getter(profiles[sid])
            if field["value"] is None:
                continue
            pairs.append((field["confidence"], bool(s[match_key])))

    calibration = calibrate.fit_calibration(pairs)
    with open(config.OUTPUTS / "confidence_calibration.json", "w", encoding="utf-8") as f:
        json.dump(calibration.to_dict(), f, indent=2)
    log(
        f"calibration fit on {len(pairs)} (confidence, correct) pairs -> "
        f"bin accuracies {calibration.bin_accuracy}"
    )

    for field_name, getter, _ in FIELD_SPECS:
        for sid in seller_ids:
            field = getter(profiles[sid])
            field["calibrated_confidence"] = calibration.apply(field["confidence"]) if field["value"] else None

    # --- bonus: catalog-health tie-in --------------------------------------
    catalog_bonus = {"sellers_with_catalog_gaps_and_invoice_products": 0, "products_price_fillable": 0}
    for sid in seller_ids:
        health = catalog_health_by_id.get(sid)
        products = profiles[sid]["products_mentioned"]
        if health and products and (health.get("products_without_price", 0) or health.get("products_without_specs", 0)):
            catalog_bonus["sellers_with_catalog_gaps_and_invoice_products"] += 1
            catalog_bonus["products_price_fillable"] += sum(1 for p in products if p.get("price_per_unit"))
    summary["catalog_health_bonus"] = catalog_bonus

    # --- write outputs -------------------------------------------------
    config.OUTPUTS.mkdir(exist_ok=True)

    enriched_out = {}
    for sid in seller_ids:
        enriched_out[sid] = {
            "profile": profiles[sid],
            "category_suggestions": category_suggestions[sid],
        }
    with open(config.OUTPUTS / "enriched_profiles.json", "w", encoding="utf-8") as f:
        json.dump(enriched_out, f, default=str)

    with open(config.OUTPUTS / "validation_per_seller.json", "w", encoding="utf-8") as f:
        json.dump(per_seller_scores, f, default=str)

    with open(config.OUTPUTS / "metrics_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    log(f"done in {round(time.time()-t0,1)}s. Summary:")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only process first N sellers (debug)")
    args = parser.parse_args()
    main(limit=args.limit)
