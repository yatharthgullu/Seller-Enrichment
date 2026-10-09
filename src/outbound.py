"""
Outbound confirmation calls through an agent hosted on Sarvam's dashboard.

Flow
  1. build_agent_variables()  -> what the agent should confirm / collect
  2. place_call()             -> POST .../outbounds, returns an attempt_id
  3. the call happens; results come back through src/sarvam_calls.py
     (webhook, or the 'Fetch latest calls' button)

Calls are normally placed by hand from the Sarvam dashboard; place_call() is
kept for workspaces where the outbound API is enabled. Config comes from env
vars or the git-ignored .env file; nothing secret lives in code.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from src import config
from src.voice import env_value

BASE_URL = "https://apps.sarvam.ai/api/outbounds/v1"
CALLS_DIR = config.OUTPUTS / "calls"
TIMEOUT = 30

UNCONFIRMED = {"", "unconfirmed", "not_confirmed", "unknown", "none", "n/a", "na", "null"}

LANGUAGE_NAME = {"en-IN": "English", "hi-IN": "Hindi"}
OPENING = {
    "English": "Hello, this is IndiaMART calling for {name}. Is this a good time for a one-minute profile check?",
    "Hindi": "नमस्ते, मैं इंडियामार्ट से {name} के लिए बात कर रहा हूँ। क्या अभी एक मिनट बात कर सकते हैं?",
}


class OutboundError(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# configuration
# ----------------------------------------------------------------------------

@dataclass
class OutboundConfig:
    api_key: str | None
    org_id: str | None
    workspace_id: str | None
    agent_id: str | None
    agent_version: str | None
    connection_id: str | None
    agent_phone: str | None
    webhook_url: str | None
    webhook_token: str | None
    initial_state: str | None

    # (env var, attribute) pairs that must be present to place a call
    REQUIRED = [
        ("SARVAM_APPS_API_KEY", "api_key"),
        ("SARVAM_ORG_ID", "org_id"),
        ("SARVAM_WORKSPACE_ID", "workspace_id"),
        ("SARVAM_AGENT_ID", "agent_id"),
        ("SARVAM_AGENT_VERSION", "agent_version"),
        ("SARVAM_CONNECTION_ID", "connection_id"),
        ("SARVAM_AGENT_PHONE", "agent_phone"),
    ]

    @classmethod
    def from_env(cls) -> "OutboundConfig":
        return cls(
            # the apps platform may use its own key; fall back to the API key
            api_key=env_value("SARVAM_APPS_API_KEY") or env_value("SARVAM_API_KEY"),
            org_id=env_value("SARVAM_ORG_ID"),
            workspace_id=env_value("SARVAM_WORKSPACE_ID"),
            agent_id=env_value("SARVAM_AGENT_ID"),
            agent_version=env_value("SARVAM_AGENT_VERSION"),
            connection_id=env_value("SARVAM_CONNECTION_ID"),
            agent_phone=env_value("SARVAM_AGENT_PHONE"),
            webhook_url=env_value("WEBHOOK_URL"),
            webhook_token=env_value("WEBHOOK_TOKEN"),
            initial_state=env_value("SARVAM_INITIAL_STATE"),
        )

    def missing(self) -> list[str]:
        return [env for env, attr in self.REQUIRED if not getattr(self, attr)]

    def full_webhook_url(self) -> str | None:
        if not self.webhook_url:
            return None
        if self.webhook_token:
            sep = "&" if "?" in self.webhook_url else "?"
            return f"{self.webhook_url}{sep}token={self.webhook_token}"
        return self.webhook_url


def normalize_phone(raw: str) -> str:
    """Return E.164 (+91XXXXXXXXXX). Bare 10-digit Indian mobiles get +91."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("+"):
        out = "+" + re.sub(r"\D", "", digits)
    else:
        d = re.sub(r"\D", "", digits)
        if len(d) == 10 and d[0] in "6789":
            out = "+91" + d
        elif len(d) == 12 and d.startswith("91"):
            out = "+" + d
        elif len(d) == 11 and d.startswith("0"):
            out = "+91" + d[1:]
        else:
            out = "+" + d
    if not re.fullmatch(r"\+\d{10,15}", out):
        raise OutboundError("Enter a valid phone number, e.g. +919876543210.")
    return out


# ----------------------------------------------------------------------------
# building the call
# ----------------------------------------------------------------------------

def call_plan(tri: dict) -> dict:
    """Split a seller's triage into what the agent confirms vs collects."""
    confirm, collect, current = [], [], {}
    for f in tri["fields"]:
        if f["bucket"] not in ("medium", "low", "missing"):
            continue
        heard = f.get("suggested") or f.get("value")
        if heard:
            confirm.append(f["key"])
            current[f["key"]] = str(heard)
        else:
            collect.append(f["key"])
    return {"confirm": confirm, "collect": collect, "current": current}


def build_agent_variables(tri: dict, company_name: str | None) -> dict:
    """Input variables for the agent. All values are strings."""
    plan = call_plan(tri)
    values = {f"{k}_current": plan["current"].get(k, "") for k in
              ("company_name", "gstin", "legal_status", "city", "state", "pincode")}
    return {
        "business_name": company_name or "",
        "fields_to_confirm": ", ".join(plan["confirm"]),
        "fields_to_collect": ", ".join(plan["collect"]),
        **values,
    }


def _mask(phone: str) -> str:
    return phone[:3] + "*" * max(0, len(phone) - 7) + phone[-4:]


def place_call(cfg: OutboundConfig, phone: str, variables: dict, *, seller_id: str,
               language_name: str, plan: dict, company_name: str | None) -> str:
    """Create the outbound call. Returns the attempt_id and records the call
    (what we asked, with what values) so the webhook result can be matched."""
    missing = cfg.missing()
    if missing:
        raise OutboundError("Missing configuration: " + ", ".join(missing))
    to_number = normalize_phone(phone)
    try:
        agent_version = int(cfg.agent_version)
    except (TypeError, ValueError) as e:
        raise OutboundError("SARVAM_AGENT_VERSION must be an integer.") from e

    overrides = {"initial_bot_message": OPENING[language_name].format(name=company_name or "your business"),
                 "initial_language_name": language_name}
    if cfg.initial_state:
        overrides["initial_state_name"] = cfg.initial_state

    body = {
        "app_config": {
            "app_id": cfg.agent_id,
            "app_version": agent_version,
            "app_type": "agent",
            "connection_config": {"connection_id": cfg.connection_id, "agent_phone_number": cfg.agent_phone},
            "agent_variables": variables,
            "app_overrides": overrides,
        },
        "user_config": {"user_phone_number": to_number},
    }
    hook = cfg.full_webhook_url()
    if hook:
        body["webhook_config"] = {"url": hook, "metadata": {"seller_id": seller_id, "source": "seller-enrichment"}}

    url = f"{BASE_URL}/orgs/{cfg.org_id}/workspaces/{cfg.workspace_id}/outbounds"
    try:
        r = requests.post(url, json=body, timeout=TIMEOUT,
                          headers={"Content-Type": "application/json", "X-API-Key": cfg.api_key})
    except requests.RequestException as e:
        raise OutboundError(f"Could not reach Sarvam: {e}") from e
    if r.status_code != 200:
        raise OutboundError(f"Call was not created ({r.status_code}): {r.text[:400]}")
    attempt_id = r.json().get("attempt_id")
    if not attempt_id:
        raise OutboundError(f"Unexpected response: {r.text[:300]}")

    save_call({
        "attempt_id": attempt_id, "seller_id": seller_id, "phone": _mask(to_number),
        "placed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "language": language_name,
        "asked": plan["confirm"] + plan["collect"], "current": plan["current"],
        "webhook_configured": bool(hook), "applied": False,
    })
    return attempt_id


# ----------------------------------------------------------------------------
# storage shared with the webhook receiver (plain files, no database)
# ----------------------------------------------------------------------------

def _safe_id(attempt_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(attempt_id))[:120]


def _write(path: Path, data: dict):
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def save_call(record: dict):
    _write(CALLS_DIR / f"{_safe_id(record['attempt_id'])}.call.json", record)


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()
