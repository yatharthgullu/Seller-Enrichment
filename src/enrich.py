"""
Upload-mode engine: take a seller's (or many sellers') KYC documents that
the user brings in, run the same fusion + calibration the backtest uses, and
turn the result into a *triage* -- for every field, should it be
auto-filled, confirmed with one tap, or reviewed by a human, and why.

Nothing here reads the IndiaMART answer key. A real seller has no answer
key; the score and the cross-document evidence are all there is.

Accepted upload formats (all carry the document's `llm_extraction` JSON,
i.e. the same shape IndiaMART's document AI produces):
  * CSV  -- columns like so_kyc_documents.csv: fk_glusr_usr_id (or
            seller_id), document_type (or doc_type), llm_extraction
  * JSON -- {seller_id: [doc, ...]}  |  {"seller_id": ..., "documents": [...]}
            |  [doc, ...] where doc = {seller_id?, doc_type, extraction}
"""
from __future__ import annotations

import io
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from src import config, data_loader as dl, fusion
from src.address_parser import CityMatcher
from src.calibration import CalibrationMap
from src.gstin_rules import gstin_checksum_valid
from src.taxonomy import CategoryMapper

# (key, label, getter) -- order is display order
FIELDS: list[tuple[str, str, Callable[[dict], dict]]] = [
    ("company_name", "Company / trade name", lambda p: p["company_name"]),
    ("gstin", "GSTIN", lambda p: p["gstin"]),
    ("legal_status", "Legal status", lambda p: p["legal_status"]),
    ("city", "City", lambda p: p["address"]["city"]),
    ("state", "State", lambda p: p["address"]["state"]),
    ("pincode", "Pincode", lambda p: p["address"]["pincode"]),
]
# fields the backtest calibrated (GSTIN has no full-number ground truth)
CALIBRATED_KEYS = {"company_name", "legal_status", "city", "state", "pincode"}

ACTION = {
    "high": "auto-fill",
    "medium": "confirm",
    "low": "review",
    "missing": "fill in",
    "verified": "confirmed",
}
_JUNK = {"", "na", "n/a", "none", "null", "nil", "-", "--"}


# ----------------------------------------------------------------------------
# engine (heavy objects, built once)
# ----------------------------------------------------------------------------

@dataclass
class Engine:
    city_matcher: CityMatcher
    category_mapper: CategoryMapper
    calibration: CalibrationMap | None


def load_engine() -> Engine:
    cal_path = config.OUTPUTS / "confidence_calibration.json"
    calibration = None
    if cal_path.exists():
        with open(cal_path, encoding="utf-8") as f:
            calibration = CalibrationMap.from_dict(json.load(f))
    return Engine(
        city_matcher=CityMatcher(dl.load_cities(), dl.load_states()),
        category_mapper=CategoryMapper(dl.load_taxonomy()),
        calibration=calibration,
    )


# ----------------------------------------------------------------------------
# parsing uploads
# ----------------------------------------------------------------------------

@dataclass
class ParseReport:
    docs_read: int = 0
    docs_skipped_type: int = 0
    docs_skipped_json: int = 0


def _add_doc(grouped, report: ParseReport, sid, doc_type, extraction):
    if isinstance(extraction, str):
        extraction = dl._safe_json(extraction)
    if not isinstance(extraction, dict):
        report.docs_skipped_json += 1
        return
    if doc_type not in config.EXTRACTABLE_DOC_TYPES:
        report.docs_skipped_type += 1
        return
    grouped[str(sid).strip()].append({"doc_type": doc_type, "extraction": extraction})
    report.docs_read += 1


def _pick(d: dict, *names):
    for n in names:
        if d.get(n) not in (None, ""):
            return d[n]
    return None


def parse_upload(name: str, data: bytes, report: ParseReport | None = None) -> dict[str, list[dict]]:
    """Return {seller_id: [{"doc_type", "extraction"}, ...]}."""
    report = report if report is not None else ParseReport()
    grouped: dict[str, list[dict]] = defaultdict(list)

    if name.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data), dtype=str, low_memory=False)
        cols = {c.lower(): c for c in df.columns}
        sid_c = cols.get("fk_glusr_usr_id") or cols.get("seller_id")
        type_c = cols.get("document_type") or cols.get("doc_type")
        ext_c = cols.get("llm_extraction") or cols.get("extraction")
        if not (sid_c and type_c and ext_c):
            raise ValueError(
                "CSV needs seller id (fk_glusr_usr_id / seller_id), document type "
                "(document_type / doc_type) and llm_extraction columns."
            )
        df = df[df[ext_c].notna()]
        for sid, dtype, ext in zip(df[sid_c], df[type_c], df[ext_c]):
            _add_doc(grouped, report, sid, dtype, ext)
        return dict(grouped)

    payload = json.loads(data.decode("utf-8-sig"))
    fallback_id = Path(name).stem

    def walk_docs(sid, docs):
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            _add_doc(
                grouped, report,
                _pick(doc, "seller_id", "fk_glusr_usr_id") or sid or fallback_id,
                _pick(doc, "doc_type", "document_type"),
                _pick(doc, "extraction", "llm_extraction"),
            )

    if isinstance(payload, list):
        walk_docs(None, payload)
    elif isinstance(payload, dict) and isinstance(payload.get("documents"), list):
        walk_docs(_pick(payload, "seller_id", "fk_glusr_usr_id"), payload["documents"])
    elif isinstance(payload, dict):
        for sid, docs in payload.items():
            if isinstance(docs, list):
                walk_docs(sid, docs)
    else:
        raise ValueError("Unrecognised JSON layout.")
    return dict(grouped)


# ----------------------------------------------------------------------------
# enrichment
# ----------------------------------------------------------------------------

def enrich(
    grouped: dict[str, list[dict]],
    engine: Engine,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict]:
    """Fuse -> calibrate -> category-suggest every seller. Same code path as
    scripts/run_pipeline.py, minus the backtest."""
    out: dict[str, dict] = {}
    total = len(grouped)
    for i, (sid, docs) in enumerate(grouped.items(), 1):
        profile = fusion.build_seller_profile(sid, docs, engine.city_matcher)
        if engine.calibration is not None:
            for key, _, getter in FIELDS:
                if key in CALIBRATED_KEYS:
                    f = getter(profile)
                    f["calibrated_confidence"] = (
                        engine.calibration.apply(f["confidence"]) if f["value"] else None
                    )
        out[sid] = {
            "profile": profile,
            "category_suggestions": engine.category_mapper.suggest_for_profile(profile, top_k=5),
        }
        if progress and (i % 25 == 0 or i == total):
            progress(i, total)
    return out


# ----------------------------------------------------------------------------
# triage
# ----------------------------------------------------------------------------

def _norm(v) -> str:
    return str(v).strip().lower()


def _bucket(conf: float) -> str:
    if conf >= config.CONFIDENCE_HIGH:
        return "high"
    if conf >= config.CONFIDENCE_MED:
        return "medium"
    return "low"


def _alternatives(field: dict, chosen, well_formed: Callable[[str], bool] | None = None):
    """Other distinct, non-junk values seen in the documents, strongest first,
    plus whether the disagreement is *material*.

    Material = the dissenting documents (those outside the winning cluster)
    carry at least half the winner's total source weight. A lone low-trust
    cheque disagreeing with two agreeing documents is shown, but is already
    priced into the calibrated confidence, so it must not demote the field a
    second time.
    """
    sources = set(field.get("sources", []))
    chosen_n = _norm(chosen) if chosen else None
    weight_by_value: dict[str, float] = defaultdict(float)
    display: dict[str, str] = {}
    winner_w = dissent_w = 0.0
    for c in field.get("all_candidates", []):
        v = c.get("value")
        if v is None or _norm(v) in _JUNK:
            continue
        if well_formed and not well_formed(str(v)):
            continue
        w = c.get("weight", 0)
        if c.get("doc_type") in sources:
            winner_w += w
        if _norm(v) != chosen_n:
            weight_by_value[_norm(v)] += w
            display.setdefault(_norm(v), str(v).strip())
            if c.get("doc_type") not in sources:
                dissent_w += w
    ranked = sorted(weight_by_value, key=weight_by_value.get, reverse=True)
    material = bool(ranked) and winner_w > 0 and dissent_w >= 0.5 * winner_w
    return [display[k] for k in ranked], material


def _degrade(bucket: str) -> str:
    return {"high": "medium"}.get(bucket, bucket)


def triage_profile(entry: dict, corrections: dict | None = None) -> dict:
    """Decide, per field, auto-fill / confirm / review, with plain reasons.

    The bucket starts from the calibrated confidence (raw for GSTIN), then
    cross-document evidence can only *lower* it (conflict, GSTIN/state
    disagreement) or, for GSTIN, be adjusted by the check-digit test.
    A seller-supplied correction overrides everything.
    """
    p = entry["profile"]
    corrections = corrections or {}
    sig = p.get("gstin_signals") or {}
    rows = []

    for key, label, getter in FIELDS:
        f = getter(p)
        value = f.get("value")
        raw = f.get("confidence", 0.0)
        conf = f.get("calibrated_confidence")
        conf = raw if conf is None else conf
        sources = f.get("sources", [])
        if key == "legal_status":
            alts, material = [], False
        else:
            alts, material = _alternatives(
                f, value, (lambda g: gstin_checksum_valid(g) is not None) if key == "gstin" else None
            )
        reasons: list[str] = []
        suggestion = None

        if not value:
            bucket = "missing"
            reasons.append("No document yielded this field")
        else:
            bucket = _bucket(conf)

            if key == "gstin":
                valid = gstin_checksum_valid(value)
                if valid is None:
                    bucket = "low"
                    reasons.append("Not a well-formed 15-character GSTIN")
                elif valid:
                    reasons.append("GSTIN check digit is valid")
                    # a valid check digit is strong, independent evidence
                    # that the characters were read correctly
                    bucket = "high" if not material else "medium"
                else:
                    good = [a for a in alts if gstin_checksum_valid(a)]
                    bucket = "low"
                    reasons.append("GSTIN fails its check digit (likely an OCR misread)")
                    if good:
                        suggestion = good[0]
                        bucket = "medium"
                        reasons.append(f"Another document's reading '{good[0]}' passes the check digit")

            elif key == "legal_status":
                reasons.append(f"Derived from GSTIN entity character '{sig.get('pan_entity_char', '?')}'")
                if gstin_checksum_valid(p["gstin"]["value"] or "") is False:
                    bucket = _degrade(bucket)
                    reasons.append("Source GSTIN fails its check digit, so this is less certain")

            elif key == "state" and sig.get("state_name") and _norm(sig["state_name"]) != _norm(value):
                bucket = _degrade(bucket)
                reasons.append(f"GSTIN state code says {sig['state_name']}")

            if key != "gstin" and key != "legal_status":
                if len(sources) >= 2:
                    reasons.append(f"Agreed by {len(sources)} documents ({', '.join(sources)})")
                elif sources:
                    reasons.append(f"Seen in one document only ({sources[0]})")
            if alts:
                shown = ", ".join(f"'{a}'" for a in alts[:3])
                if material:
                    reasons.append(f"Documents disagree: also read as {shown}")
                    if key != "gstin":
                        bucket = _degrade(bucket)
                else:
                    reasons.append(f"Minor: a lower-trust document read {shown}")

        final_value, final_conf, final_bucket = value, conf if value else None, bucket
        if key in corrections:
            final_value, final_conf, final_bucket = corrections[key]["new_value"], 1.0, "verified"
            reasons = ["Confirmed by seller"] + reasons

        rows.append({
            "key": key,
            "label": label,
            "value": final_value,
            "predicted_value": value,
            "confidence": final_conf,
            "raw_confidence": raw if value else None,
            "bucket": final_bucket,
            "action": ACTION[final_bucket],
            "reasons": reasons,
            "alternatives": ([suggestion] if suggestion else []) + [a for a in alts if a != suggestion],
            "suggested": suggestion,
            "material_conflict": material,
            "sources": sources,
        })

    attention = [r for r in rows if r["bucket"] in ("medium", "low", "missing")]
    return {
        "seller_id": p["seller_id"],
        "fields": rows,
        "needs_attention": len(attention),
        "ready": not attention,
        "risk_flags": p.get("risk_flags", []),
    }


# ----------------------------------------------------------------------------
# export
# ----------------------------------------------------------------------------

def triage_to_row(entry: dict, tri: dict) -> dict:
    row = {"seller_id": tri["seller_id"], "doc_count": entry["profile"]["doc_count"]}
    for r in tri["fields"]:
        k = r["key"]
        row[k] = r["value"]
        row[f"{k}_confidence"] = r["confidence"]
        row[f"{k}_status"] = r["action"]
    cats = entry.get("category_suggestions") or []
    row["category_suggestions"] = " | ".join(c["category_name"] for c in cats[:3])
    row["fields_needing_attention"] = tri["needs_attention"]
    row["review_fields"] = ", ".join(r["key"] for r in tri["fields"] if r["bucket"] in ("medium", "low", "missing"))
    row["risk_flags"] = "|".join(tri["risk_flags"])
    return row
