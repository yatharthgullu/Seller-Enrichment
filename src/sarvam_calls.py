"""
Calls triggered from the Sarvam dashboard, matched back to sellers by GLID.

The call is placed by hand (dashboard test call, or a campaign over a cohort
CSV). Results reach us two ways, both ending in outputs/calls/:
  * push : Sarvam POSTs a webhook per attempt -> scripts/webhook_server.py
  * pull : fetch_recent() reads the analytics "attempts" API (the Streamlit
           button), for when no webhook is configured or it was missed

Either way a raw payload is turned by normalize() into one flat record, and
field_mapping() lays that record out per profile field: what was on file,
whether the agent confirmed / corrected / collected it, and the new value.

GLID is read from, in order: the `glid` agent variable, webhook metadata
(glid / seller_id), and user_identifier only if it is not Sarvam's SHA-256 hash.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from src import config
from src.outbound import CALLS_DIR, OutboundConfig, OutboundError, UNCONFIRMED, _norm, _safe_id, _write, load_json

ANALYTICS_URL = "https://apps.sarvam.ai/api/analytics/v1/{org}/{ws}/{app}"
TIMEOUT = 30
PAGE = 100
# Sarvam's analytics API returns user_identifier as a SHA-256 hash, not the id we set
_HASH = re.compile(r"[0-9a-fA-F]{64}")
FIELDS = ["company_name", "gstin", "legal_status", "city", "state", "pincode"]
FIELD_LABEL = {"company_name": "Company name", "gstin": "GSTIN", "legal_status": "Legal status",
               "city": "City", "state": "State", "pincode": "Pincode"}


# ----------------------------------------------------------------------------
# raw payload -> flat record
# ----------------------------------------------------------------------------

def _vars(*maps) -> dict:
    """Merge variable maps; later maps win, blanks never overwrite a value."""
    out: dict = {}
    for m in maps:
        for k, v in (m or {}).items():
            if v not in (None, "") or k not in out:
                out[k] = v
    return out


def _status(p: dict) -> str:
    """connected | no_answer | busy | failed | unknown, across the three payload shapes."""
    raw = p.get("connectivity_status") or p.get("status")
    if raw in ("connected", "no_answer", "busy", "failed"):
        return raw
    if p.get("duration") or p.get("duration_in_seconds"):
        return "connected"
    return "unknown"


def normalize(p: dict) -> dict:
    """Webhook payload (campaign or instant) or an analytics attempts row -> flat record."""
    final = _vars(p.get("initial_agent_variables"), p.get("agent_variables"),
                  p.get("output_agent_variables"), p.get("final_agent_variables"))
    meta = p.get("metadata") or (p.get("webhook_config") or {}).get("metadata") or {}
    glid = next((str(x).strip() for x in (final.get("glid"), p.get("user_identifier"),
                                           meta.get("glid"), meta.get("seller_id"))
                 if x and str(x).strip() and not _HASH.fullmatch(str(x).strip())), "")
    return {
        "attempt_id": p.get("attempt_id"),
        "glid": glid,
        "status": _status(p),
        "failure_reason": p.get("failure_reason"),
        "duration": p.get("duration") if p.get("duration") is not None else p.get("duration_in_seconds"),
        "started": p.get("start_datetime") or p.get("executed_at"),
        "interaction_id": p.get("interaction_id"),
        "campaign_id": p.get("campaign_id"),
        "variables": final,
        "transcript": p.get("interaction_transcript") or [],
        "source": "webhook" if "completion_status" in p or "webhook_config" in p else "api",
    }


def _split_pairs(text) -> dict:
    """'city: Pune; pincode: 411001' -> {'city': 'Pune', 'pincode': '411001'}"""
    out = {}
    for part in re.split(r"[;\n]", str(text or "")):
        key, sep, val = part.partition(":")
        key = re.sub(r"[^a-z_]", "", key.strip().lower().replace(" ", "_"))
        if sep and key in FIELDS and val.strip() and _norm(val) not in UNCONFIRMED:
            out[key] = val.strip()
    return out


def _split_list(text) -> set:
    return {re.sub(r"[^a-z_]", "", t.strip().lower().replace(" ", "_"))
            for t in re.split(r"[,;]", str(text or "")) if _norm(t) not in UNCONFIRMED}


def field_mapping(rec: dict) -> list[dict]:
    """One row per profile field: asked?, on file, outcome, value to apply.

    outcome: confirmed | corrected | collected | not confirmed | not asked.
    `value` is set only for outcomes that may be written to the profile.
    """
    v = rec["variables"]
    to_confirm, to_collect = _split_list(v.get("fields_to_confirm")), _split_list(v.get("fields_to_collect"))
    confirmed = _split_list(v.get("confirmed_fields"))
    updated, collected = _split_pairs(v.get("updated_fields")), _split_pairs(v.get("collected_values"))
    reported = confirmed | set(updated) | set(collected)
    rows = []
    for key in FIELDS:
        on_file = str(v.get(f"{key}_current") or "").strip()
        if key not in to_confirm and key not in to_collect and key not in reported:
            outcome, value = "not asked", None
        elif key in updated:
            outcome, value = "corrected", updated[key]
        elif key in collected:
            outcome, value = "collected", collected[key]
        elif key in confirmed:
            outcome, value = "confirmed", on_file or None
        else:
            outcome, value = "not confirmed", None
        rows.append({"key": key, "field": FIELD_LABEL[key],
                     "asked": "confirm" if key in to_confirm else "collect" if key in to_collect else "reported" if key in reported else "-",
                     "on_file": on_file, "outcome": outcome, "value": value})
    return rows


def corrections_from(rows: list[dict], engine) -> tuple[dict, list[dict]]:
    """Re-validate what the agent reported with the same rules as the rest of the
    pipeline (GSTIN check digit, pincode shape, gazetteer match) before it may
    overwrite a field. Returns (corrections for the app's store, rows with a
    `check` column explaining the verdict)."""
    from src.voice import parse_reply

    corrections, shown = {}, []
    for r in rows:
        row = {**r, "check": ""}
        if r["outcome"] == "confirmed" and r["value"]:
            corrections[r["key"]] = {"old_value": r["on_file"], "new_value": r["value"]}
            row["check"] = "ok"
        elif r["outcome"] in ("corrected", "collected"):
            parsed = parse_reply(r["key"], r["value"], "value", engine, [r["on_file"]] if r["on_file"] else [])
            if parsed["intent"] == "value":
                corrections[r["key"]] = {"old_value": r["on_file"] or None, "new_value": parsed["value"]}
                row["value"] = parsed["value"]
                row["check"] = "ok" + (f" ({parsed['note']})" if parsed["note"] else "")
            else:
                row["check"] = f"rejected: {parsed['note']}"
                row["value"] = None
        shown.append(row)
    return corrections, shown


# ----------------------------------------------------------------------------
# storage (shared with the webhook receiver)
# ----------------------------------------------------------------------------

def save_raw(payload: dict) -> str | None:
    """Store any payload that carries an attempt_id. Returns that id."""
    aid = payload.get("attempt_id")
    if not aid:
        return None
    payload = {k: v for k, v in payload.items() if k != "user_contact"}
    path = CALLS_DIR / f"{_safe_id(aid)}.result.json"
    old = load_json(path) or {}
    # a webhook payload is richer than an API row; never replace it with a poorer one
    if old.get("final_agent_variables") and not payload.get("final_agent_variables"):
        return aid
    _write(path, payload)
    return aid


def results_for_glid(glid: str) -> list[dict]:
    if not CALLS_DIR.exists():
        return []
    recs = [r for p in CALLS_DIR.glob("*.result.json") if (raw := load_json(p)) and (r := normalize(raw))["glid"] == str(glid)]
    return sorted(recs, key=lambda r: str(r.get("started") or ""), reverse=True)


def unmatched_results() -> list[dict]:
    """Stored calls with no GLID, so nothing silently disappears."""
    if not CALLS_DIR.exists():
        return []
    return [r for p in CALLS_DIR.glob("*.result.json") if (raw := load_json(p)) and not (r := normalize(raw))["glid"]]


def _applied_path(attempt_id: str) -> Path:
    return CALLS_DIR / f"{_safe_id(attempt_id)}.applied.json"


def is_applied(attempt_id: str) -> bool:
    return _applied_path(attempt_id).exists()


def mark_applied(attempt_id: str, glid: str, values: dict):
    _write(_applied_path(attempt_id), {"attempt_id": attempt_id, "glid": glid, "values": values,
                                       "applied_at": time.strftime("%Y-%m-%d %H:%M:%S")})


# ----------------------------------------------------------------------------
# pull: analytics API
# ----------------------------------------------------------------------------

def _api_cfg(cfg: OutboundConfig) -> str:
    missing = [env for env, attr in (("SARVAM_APPS_API_KEY or SARVAM_API_KEY", "api_key"), ("SARVAM_ORG_ID", "org_id"),
                                     ("SARVAM_WORKSPACE_ID", "workspace_id"), ("SARVAM_AGENT_ID", "agent_id"))
               if not getattr(cfg, attr)]
    if missing:
        raise OutboundError("Missing configuration: " + ", ".join(missing))
    return ANALYTICS_URL.format(org=cfg.org_id, ws=cfg.workspace_id, app=cfg.agent_id)


def _get(cfg: OutboundConfig, url: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT, headers={"X-API-Key": cfg.api_key})
    except requests.RequestException as e:
        raise OutboundError(f"Could not reach Sarvam: {e}") from e
    if r.status_code != 200:
        raise OutboundError(f"Sarvam returned {r.status_code}: {r.text[:300]}")
    return r.json()


def fetch_recent(cfg: OutboundConfig, hours: int = 72) -> dict:
    """Pull recent connected attempts for the agent, with their transcripts, and
    store them. Returns {"fetched", "new", "matched", "unmatched"}."""
    base = _api_cfg(cfg)
    end = datetime.now(timezone.utc)
    window = {"start_datetime": (end - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "end_datetime": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "sort_by": "start_datetime", "sort_order": "desc"}
    rows, offset = [], 0
    while True:
        page = _get(cfg, f"{base}/attempts", {**window, "limit": PAGE, "offset": offset})
        items = page.get("items") or []
        rows += items
        offset += len(items)
        if not items or offset >= (page.get("total") or 0) or offset >= 1000:
            break

    new = matched = 0
    for row in rows:
        if row.get("connectivity_status") != "connected" or not row.get("attempt_id"):
            continue
        is_new = not (CALLS_DIR / f"{_safe_id(row['attempt_id'])}.result.json").exists()
        if row.get("interaction_id") and not (load_json(CALLS_DIR / f"{_safe_id(row['attempt_id'])}.result.json") or {}).get("interaction_transcript"):
            row["interaction_transcript"] = _fetch_transcript(cfg, base, row["interaction_id"])
        save_raw(row)
        new += is_new
        matched += bool(normalize(row)["glid"])
    connected = sum(1 for r in rows if r.get("connectivity_status") == "connected")
    return {"fetched": len(rows), "connected": connected, "new": new, "matched": matched}


def _fetch_transcript(cfg: OutboundConfig, base: str, interaction_id: str) -> list[dict]:
    """Best effort: the transcript is nice to have, never a reason to fail the sync."""
    try:
        body = _get(cfg, f"{base}/transcripts/{interaction_id}")
    except OutboundError:
        return []
    return [{"role": "agent" if t.get("role") == "assistant" else t.get("role", "?"), "en_text": t.get("content") or ""}
            for t in body.get("messages") or [] if isinstance(t, dict) and t.get("content")]


# ----------------------------------------------------------------------------
# helper for the manual dashboard trigger
# ----------------------------------------------------------------------------

def dashboard_variables(glid: str, variables: dict) -> dict:
    """What to type into the dashboard's agent-variable fields for this seller."""
    return {"glid": str(glid), **variables}


def cohort_csv(glid: str, phone: str, variables: dict) -> str:
    """One-row cohort CSV: map phone_number -> phone, every other column -> the agent variable of that name (glid included)."""
    import csv
    import io
    row = {"phone_number": phone, "user_identifier": str(glid), **dashboard_variables(glid, variables)}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(row))
    w.writeheader()
    w.writerow(row)
    return buf.getvalue()
