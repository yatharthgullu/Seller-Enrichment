"""
HTTP API for the Seller Enrichment web app.

    uvicorn api.main:app --port 8000

A thin layer over the existing engine (src/): nothing here re-implements the
pipeline. It serves three things to the React app in web/:
  /api/enrich/*    upload KYC documents -> triaged, editable profiles + call results
  /api/accuracy    backtest metrics and the confidence-threshold explorer
  /api/explorer/*  one seller from the 3,000-seller backtest, next to the answer key
plus the Sarvam webhook (/sarvam/webhook) so one process serves everything.
If web/dist exists (npm run build) it is served at /.
"""
from __future__ import annotations

import hmac
import io
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, enrich as enr, outbound, sarvam_calls  # noqa: E402
from src.export import build_export_dataframe  # noqa: E402
from src.voice import env_value  # noqa: E402

SAMPLE_DIR = config.ROOT / "data" / "samples"
PACK_DIR = config.ROOT / "sample_data"   # the 10-seller test pack (scripts/make_sample_dataset.py)
CORRECTIONS_FILE = config.OUTPUTS / "corrections.json"
DIST = config.ROOT / "web" / "dist"
CALIBRATED_COLS = ["company_name_confidence", "legal_status_confidence", "city_confidence",
                   "state_confidence", "pincode_confidence"]
FIELD_LABELS = {"company_name": "Company name", "legal_status": "Legal status", "city": "City",
                "state": "State", "pincode": "Pincode"}


def _clean(o):
    """json.dumps default: numpy scalars/arrays and NaN-ish values."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


class Json(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, default=_clean, ensure_ascii=False, allow_nan=False).encode("utf-8")


# ----------------------------------------------------------------------------
# state: one analyst session (this is a single-user tool, not a multi-tenant service)
# ----------------------------------------------------------------------------

class State:
    engine = None
    enriched: dict = {}
    metrics: dict = {}
    sellers_gt: pd.DataFrame | None = None
    cats_gt: pd.DataFrame | None = None
    # the current upload
    results: dict = {}
    report = None
    corrections: dict = {}


S = State()


def _load_dataset():
    out = config.OUTPUTS
    if (out / "enriched_profiles.json").exists():
        S.enriched = json.loads((out / "enriched_profiles.json").read_text(encoding="utf-8"))
        S.metrics = json.loads((out / "metrics_summary.json").read_text(encoding="utf-8"))
    if config.F_SELLERS.exists():
        sellers = pd.read_csv(config.F_SELLERS, low_memory=False)
        sellers["fk_glusr_usr_id"] = sellers["fk_glusr_usr_id"].astype(str)
        S.sellers_gt = sellers.set_index("fk_glusr_usr_id")
    if config.F_CATEGORIES.exists():
        cats = pd.read_csv(config.F_CATEGORIES, low_memory=False)
        cats["fk_glusr_usr_id"] = cats["fk_glusr_usr_id"].astype(str)
        S.cats_gt = cats


@asynccontextmanager
async def lifespan(_: FastAPI):
    S.engine = enr.load_engine()
    _load_dataset()
    yield


app = FastAPI(title="Seller Enrichment", default_response_class=Json, lifespan=lifespan)


# ----------------------------------------------------------------------------
# corrections (same on-disk audit trail as before)
# ----------------------------------------------------------------------------

def _log_correction(sid: str, key: str, old, new: str):
    data = {}
    if CORRECTIONS_FILE.exists():
        try:
            data = json.loads(CORRECTIONS_FILE.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data.setdefault(sid, {})[key] = {"old_value": old, "new_value": new}
    CORRECTIONS_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def set_correction(sid: str, key: str, old, new: str):
    new = (new or "").strip()
    if not new:
        return
    S.corrections.setdefault(sid, {})[key] = {"old_value": old, "new_value": new}
    _log_correction(sid, key, old, new)


def _triage(sid: str) -> dict:
    if sid not in S.results:
        raise HTTPException(404, f"No uploaded seller {sid}")
    return enr.triage_profile(S.results[sid], S.corrections.get(sid))


# ----------------------------------------------------------------------------
# meta
# ----------------------------------------------------------------------------

@app.get("/api/meta")
def meta():
    cfg = outbound.OutboundConfig.from_env()
    api_missing = []
    if not cfg.api_key:
        api_missing.append("SARVAM_APPS_API_KEY")
    api_missing += [env for env, attr in (("SARVAM_ORG_ID", "org_id"), ("SARVAM_WORKSPACE_ID", "workspace_id"),
                                          ("SARVAM_AGENT_ID", "agent_id")) if not getattr(cfg, attr)]
    return {
        "thresholds": {"high": config.CONFIDENCE_HIGH, "medium": config.CONFIDENCE_MED},
        "dataset_ready": bool(S.enriched),
        "sellers_in_dataset": len(S.enriched),
        "has_samples": (PACK_DIR / "sample_10_sellers.csv").exists() or (SAMPLE_DIR / "sample_upload_multi.csv").exists(),
        "has_pack": (PACK_DIR / "sample_10_sellers.csv").exists(),
        "sarvam": {"fetch_ready": not api_missing, "missing": api_missing,
                   "webhook_ready": bool(cfg.webhook_url)},
    }


# ----------------------------------------------------------------------------
# enrich: upload -> triage
# ----------------------------------------------------------------------------

def _ingest(sources: list[tuple[str, bytes]]):
    report = enr.ParseReport()
    grouped: dict[str, list[dict]] = {}
    for name, data in sources:
        for sid, docs in enr.parse_upload(name, data, report).items():
            grouped.setdefault(sid, []).extend(docs)
    if not grouped:
        raise HTTPException(422, "No usable documents found (need doc types: "
                            + ", ".join(sorted(config.EXTRACTABLE_DOC_TYPES)) + ").")
    S.results = enr.enrich(grouped, S.engine, None)
    S.report = report
    S.corrections = {}


@app.post("/api/enrich/upload")
async def upload(files: list[UploadFile] = File(...)):
    try:
        _ingest([(f.filename or "upload", await f.read()) for f in files])
    except HTTPException:
        raise
    except Exception as e:  # malformed upload: say so, keep the server alive
        raise HTTPException(422, f"Could not read the upload: {e}") from e
    return enrich_summary()


@app.post("/api/enrich/sample")
def load_sample(which: str = "ten"):
    path = (PACK_DIR / "sample_10_sellers.csv") if which == "ten" else (SAMPLE_DIR / "sample_upload_multi.csv")
    if not path.exists():
        raise HTTPException(404, "Sample file not found")
    _ingest([(path.name, path.read_bytes())])
    return enrich_summary()


def _sample_path(name: str) -> Path | None:
    for folder in (PACK_DIR, SAMPLE_DIR):
        if "/" not in name and "\\" not in name and (folder / name).is_file():
            return folder / name
    return None


_SAMPLE_FILES = {
    "seller_enrichment_test_pack.zip": "application/zip",
    "sample_10_sellers.csv": "text/csv",
    "sample_10_sellers.json": "application/json",
    "sample_10_sellers_scenarios.csv": "text/csv",
    "README.md": "text/markdown",
    "sample_upload_multi.csv": "text/csv",
    "sample_upload_single.json": "application/json",
}


@app.get("/api/enrich/samples/{name}")
def download_sample(name: str):
    path = _sample_path(name) if name in _SAMPLE_FILES else None
    if not path:
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type=_SAMPLE_FILES[name],
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/samples/scenarios")
def sample_scenarios():
    path = PACK_DIR / "sample_10_sellers_scenarios.csv"
    if not path.exists():
        return {"scenarios": []}
    df = pd.read_csv(path, dtype=str).fillna("-")
    return {"scenarios": df.to_dict(orient="records")}


@app.get("/api/enrich")
def enrich_summary():
    if not S.results:
        return {"loaded": False}
    triages = {sid: enr.triage_profile(e, S.corrections.get(sid)) for sid, e in S.results.items()}
    fields = [f for t in triages.values() for f in t["fields"]]
    n_auto = sum(f["bucket"] in ("high", "verified") for f in fields)
    sellers = [{
        "id": sid, "docs": S.results[sid]["profile"]["doc_count"], "ready": t["ready"],
        "needs_attention": t["needs_attention"], "risk_flags": t["risk_flags"],
        "check": [f["key"] for f in t["fields"] if f["bucket"] in ("medium", "low", "missing")],
    } for sid, t in triages.items()]
    r = S.report
    return {
        "loaded": True, "sellers": sellers,
        "stats": {"sellers": len(triages), "auto_pct": round(n_auto / len(fields) * 100) if fields else 0,
                  "ready": sum(t["ready"] for t in triages.values()), "needs_person": len(fields) - n_auto},
        "report": {"docs_read": r.docs_read, "skipped_type": r.docs_skipped_type, "skipped_json": r.docs_skipped_json},
    }


@app.get("/api/enrich/sellers/{sid}")
def enrich_seller(sid: str):
    tri = _triage(sid)
    entry = S.results[sid]
    p = entry["profile"]
    return {"id": sid, "triage": tri, "doc_count": p["doc_count"], "doc_types": p["doc_types_seen"],
            "categories": entry["category_suggestions"],
            "corrections": S.corrections.get(sid, {})}


@app.post("/api/enrich/sellers/{sid}/correct")
def correct(sid: str, body: dict = Body(...)):
    tri = _triage(sid)
    key, value = body.get("key"), str(body.get("value") or "")
    field = next((f for f in tri["fields"] if f["key"] == key), None)
    if not field:
        raise HTTPException(422, f"Unknown field {key}")
    if not value.strip():
        raise HTTPException(422, "Value is empty")
    set_correction(sid, key, field["predicted_value"], value)
    return enrich_seller(sid)


@app.get("/api/enrich/export.csv")
def export_csv():
    triages = {sid: enr.triage_profile(e, S.corrections.get(sid)) for sid, e in S.results.items()}
    df = pd.DataFrame([enr.triage_to_row(S.results[sid], triages[sid]) for sid in triages])
    return Response(df.to_csv(index=False).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="enriched_sellers.csv"'})


@app.get("/api/enrich/export.json")
def export_json():
    out = {}
    for sid, e in S.results.items():
        out[sid] = {"triage": enr.triage_profile(e, S.corrections.get(sid)), "profile": e["profile"]}
    return Response(json.dumps(out, default=_clean).encode("utf-8"), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="enriched_sellers.json"'})


# ----------------------------------------------------------------------------
# phone verification: variables for the Sarvam dashboard + call results by GLID
# ----------------------------------------------------------------------------

@app.get("/api/enrich/sellers/{sid}/call")
def call_setup(sid: str, phone: str = ""):
    tri = _triage(sid)
    plan = outbound.call_plan(tri)
    company = next((f["value"] for f in tri["fields"] if f["key"] == "company_name"), None)
    variables = outbound.build_agent_variables(tri, company)
    return {"plan": plan, "variables": sarvam_calls.dashboard_variables(sid, variables),
            "csv": sarvam_calls.cohort_csv(sid, phone, variables)}


def _call_view(rec: dict) -> dict:
    corrections, rows = sarvam_calls.corrections_from(sarvam_calls.field_mapping(rec), S.engine)
    v = rec["variables"]
    return {
        "attempt_id": rec["attempt_id"], "glid": rec["glid"], "started": rec["started"], "source": rec["source"],
        "status": rec["status"], "duration": rec["duration"], "failure_reason": rec["failure_reason"],
        "disposition": v.get("call_disposition") or None, "summary": v.get("call_summary") or None,
        "rows": [{k: r[k] for k in ("key", "field", "asked", "on_file", "outcome", "value", "check")} for r in rows],
        "applicable": len(corrections), "applied": sarvam_calls.is_applied(rec["attempt_id"]),
        "transcript": rec["transcript"],
    }


@app.get("/api/calls")
def calls(glid: str):
    return {"calls": [_call_view(r) for r in sarvam_calls.results_for_glid(glid)[:5]],
            "unmatched": len(sarvam_calls.unmatched_results())}


@app.post("/api/calls/sync")
def calls_sync(body: dict = Body(default={})):
    hours = int(body.get("hours") or 72)
    try:
        return sarvam_calls.fetch_recent(outbound.OutboundConfig.from_env(), hours)
    except outbound.OutboundError as e:
        raise HTTPException(502, str(e)) from e


@app.post("/api/calls/{attempt_id}/apply")
def calls_apply(attempt_id: str, body: dict = Body(...)):
    glid = str(body.get("glid") or "")
    rec = next((r for r in sarvam_calls.results_for_glid(glid) if r["attempt_id"] == attempt_id), None)
    if not rec:
        raise HTTPException(404, "No such call for this seller")
    if sarvam_calls.is_applied(attempt_id):
        raise HTTPException(409, "Already applied")
    corrections, _ = sarvam_calls.corrections_from(sarvam_calls.field_mapping(rec), S.engine)
    if not corrections:
        raise HTTPException(422, "Nothing confirmed on this call")
    for key, c in corrections.items():
        set_correction(glid, key, c["old_value"], c["new_value"])
    sarvam_calls.mark_applied(attempt_id, glid, {k: c["new_value"] for k, c in corrections.items()})
    return {"applied": list(corrections)}


@app.post("/api/calls/paste")
def calls_paste(payload: dict = Body(...)):
    if not payload.get("attempt_id"):
        raise HTTPException(422, "JSON needs an attempt_id")
    sarvam_calls.save_raw(payload)
    return {"glid": sarvam_calls.normalize(payload)["glid"]}


@app.post("/sarvam/webhook")
async def webhook(request: Request, token: str = ""):
    expected = env_value("WEBHOOK_TOKEN")
    if expected and not hmac.compare_digest(token, expected):
        raise HTTPException(403, "bad token")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "bad json")
    if not isinstance(payload, dict) or not sarvam_calls.save_raw(payload):
        raise HTTPException(400, "no attempt_id")
    return {"ok": True}


# ----------------------------------------------------------------------------
# accuracy: backtest metrics + threshold explorer
# ----------------------------------------------------------------------------

def _export_df() -> pd.DataFrame:
    return build_export_dataframe(S.enriched)


@app.get("/api/accuracy")
def accuracy(threshold: float = Query(config.CONFIDENCE_HIGH, ge=0, le=1)):
    m = S.metrics
    if not m:
        return {"loaded": False}
    df = _export_df()
    passes = df[CALIBRATED_COLS].fillna(-1) >= threshold  # a missing field is not a pass
    per_field = [{"key": c.replace("_confidence", ""), "label": FIELD_LABELS[c.replace("_confidence", "")],
                  "rate": float(passes[c].mean())} for c in CALIBRATED_COLS]
    return {
        "loaded": True, "sellers": m["sellers_scored"],
        "headline": [
            {"key": "company_name", "label": "Company name", "rate": m["company_name_match_rate"]["rate"],
             "note": f"n={m['company_name_match_rate']['n']}, fuzzy match ≥ 80"},
            {"key": "gstin", "label": "GSTIN entity character", "rate": m["gstin_6th_char_match_rate"]["rate"],
             "note": "validated through the privacy-safe 6th-character field"},
            {"key": "legal_status", "label": "Legal status", "rate": m["legal_status_match_rate"]["rate"],
             "note": "derived from the GSTIN's PAN entity-type character"},
            {"key": "city", "label": "City", "rate": m["city_match_rate"]["rate"], "note": f"n={m['city_match_rate']['n']}"},
            {"key": "state", "label": "State", "rate": m["state_match_rate"]["rate"], "note": f"n={m['state_match_rate']['n']}"},
            {"key": "pincode", "label": "Pincode", "rate": m["pincode_match_rate"]["rate"], "note": f"n={m['pincode_match_rate']['n']}"},
        ],
        "coverage": {"rate": m["field_coverage_rate"], "avg_fields": m["avg_fields_populated"],
                     "total_fields": m["fields_total_per_seller"]},
        "category_top5": {"rate": m["category_top5_precision"]["avg"], "n": m["category_top5_precision"]["n"]},
        "catalog": m["catalog_health_bonus"],
        "threshold": {
            "value": threshold, "per_field": per_field,
            "field_pass_rate": float(passes.values.mean()),
            "sellers_all_pass": int(passes.all(axis=1).sum()),
            "sellers_need_review": int((~passes.all(axis=1)).sum()),
        },
    }


@app.get("/api/accuracy/predictions.csv")
def predictions_csv():
    return Response(_export_df().to_csv(index=False).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="seller_enrichment_predictions.csv"'})


@app.get("/api/accuracy/profiles.json")
def profiles_json():
    return Response(json.dumps(S.enriched, default=_clean).encode("utf-8"), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="seller_enrichment_profiles_full.json"'})


# ----------------------------------------------------------------------------
# explorer: one backtest seller next to the answer key
# ----------------------------------------------------------------------------

@app.get("/api/explorer/sellers")
def explorer_list(q: str = "", limit: int = 200):
    rows = [{"id": sid, "docs": e["profile"]["doc_count"], "flags": len(e["profile"]["risk_flags"])}
            for sid, e in S.enriched.items() if q in sid]
    rows.sort(key=lambda r: (-r["docs"], r["id"]))
    return {"total": len(rows), "sellers": rows[:limit]}


def _field(f: dict) -> dict:
    conf = f.get("calibrated_confidence")
    return {"value": f.get("value"), "confidence": conf if conf is not None else f.get("confidence", 0.0),
            "raw_confidence": f.get("confidence", 0.0), "calibrated": conf is not None,
            "sources": f.get("sources", []), "candidates": f.get("all_candidates", [])}


@app.get("/api/explorer/sellers/{sid}")
def explorer_seller(sid: str):
    entry = S.enriched.get(sid)
    if not entry:
        raise HTTPException(404, f"No seller {sid}")
    p = entry["profile"]
    truth = {}
    if S.sellers_gt is not None and sid in S.sellers_gt.index:
        t = S.sellers_gt.loc[sid].to_dict()
        pick = lambda k: None if k not in t or pd.isna(t[k]) else str(t[k])  # noqa: E731
        truth = {"company_name": pick("company_name"), "legal_status": pick("legal_status"), "city": pick("city_name"),
                 "state": pick("state_name"), "pincode": pick("pincode"),
                 "partners": pick("gst_partner_names"), "designation": pick("contact_designation")}
    true_cats = set()
    if S.cats_gt is not None:
        true_cats = set(S.cats_gt[S.cats_gt["fk_glusr_usr_id"] == sid]["category_name"].tolist())
    return {
        "id": sid, "doc_count": p["doc_count"], "doc_types": p["doc_types_seen"], "risk_flags": p["risk_flags"],
        "fields": {"company_name": _field(p["company_name"]), "gstin": _field(p["gstin"]),
                   "legal_status": _field(p["legal_status"]), "city": _field(p["address"]["city"]),
                   "state": _field(p["address"]["state"]), "pincode": _field(p["address"]["pincode"])},
        "raw_address": p["address"]["raw_text"]["value"],
        "truth": truth,
        "categories": [{"category": c["category_name"], "group": c["group_name"], "confidence": c["confidence"],
                        "real": c["category_name"] in true_cats} for c in entry["category_suggestions"]],
        "products": p["products_mentioned"],
    }


@app.get("/api/explorer/sellers/{sid}/profile.json")
def explorer_download(sid: str):
    if sid not in S.enriched:
        raise HTTPException(404)
    return Response(json.dumps(S.enriched[sid], default=_clean, indent=2).encode("utf-8"),
                    media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="seller_{sid}_profile.json"'})


# ----------------------------------------------------------------------------
# static front end (after `npm run build` in web/)
# ----------------------------------------------------------------------------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "sarvam/")):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        return FileResponse(f if f.is_file() and DIST in f.parents else DIST / "index.html")
