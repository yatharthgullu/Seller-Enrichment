"""
Turning spoken or reported answers into validated profile values.

parse_reply() takes what the seller said (a call transcript fragment, or a value
the agent reported) and returns yes | no | a clean value for the field. It is
rule-based and deterministic (yes/no words in English + Hindi, spoken digits,
gazetteer fuzzy match, GSTIN check digit), so a mis-hearing is caught by the same
validators the rest of the pipeline uses instead of being trusted blindly.

Also holds env_value(), the .env reader the rest of the project uses.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import requests
from rapidfuzz import fuzz, process

from src import config
from src.gstin_rules import PAN_CHAR_TO_LEGAL_STATUS, gstin_checksum_valid

TIMEOUT = 40


class VoiceError(RuntimeError):
    pass


# ----------------------------------------------------------------------------
# Sarvam client (plain REST; no compiled dependencies)
# ----------------------------------------------------------------------------

def env_value(name: str) -> str | None:
    """Env var first, then a git-ignored .env file at the project root."""
    val = os.environ.get(name)
    if val and val.strip():
        return val.strip()
    env_file = config.ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip('"').strip("'")
    return None


def get_api_key() -> str | None:
    return env_value("SARVAM_API_KEY")


def _headers() -> dict:
    key = get_api_key()
    if not key:
        raise VoiceError("SARVAM_API_KEY is not set (put it in .env at the project root).")
    return {"api-subscription-key": key}


def _error_text(resp: requests.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("error", body))[:300]
    except ValueError:
        return resp.text[:300]


# ----------------------------------------------------------------------------
# understanding the reply
# ----------------------------------------------------------------------------

YES = {"yes", "yeah", "yep", "yup", "correct", "right", "sure", "ok", "okay", "confirm", "confirmed",
       "haan", "han", "haa", "ha", "ji", "jee", "sahi", "theek", "thik", "bilkul", "हाँ", "हां", "जी", "सही",
       "ठीक", "बिल्कुल"}
NO = {"no", "nope", "nah", "wrong", "incorrect", "not", "nahi", "nahin", "nhi", "galat", "नहीं", "नही", "गलत"}
POLITE = {"that", "thats", "that's", "is", "it", "its", "it's", "so", "this", "the", "please", "thank",
          "thanks", "you", "hai", "he", "है", "वो", "यह", "ये", "और"}

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4", "paanch": "5",
    "panch": "5", "chhe": "6", "chhah": "6", "che": "6", "saat": "7", "aath": "8", "nau": "9",
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5", "छह": "6",
    "छः": "6", "सात": "7", "आठ": "8", "नौ": "9",
}
_REPEAT = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3}

_LEAD_FILLER = re.compile(
    r"^(?:(?:my|our|the|its|it's|it|is|company|business|firm|shop|name|called|city|state|located|in|at|"
    r"from|mera|meri|hamara|hamari|humara|naam|shehar|sheher|rajya|hai)\s+)+", re.I)
_TRAIL_FILLER = re.compile(r"(?:\s+(?:hai|है|please|thanks|thank you))+$", re.I)

_LEGAL_KEYWORDS = [
    (("private limited", "pvt", "limited", "ltd", "company", "प्राइवेट", "लिमिटेड", "कंपनी"),
     PAN_CHAR_TO_LEGAL_STATUS["C"]),
    (("partnership", "partner", "firm", "पार्टनरशिप", "साझेदारी"), PAN_CHAR_TO_LEGAL_STATUS["F"]),
    (("huf", "hindu undivided", "हिंदू अविभाजित"), PAN_CHAR_TO_LEGAL_STATUS["H"]),
    (("proprietor", "proprietorship", "individual", "sole", "owner", "प्रोप्राइटर", "प्रोप्राइटरशिप", "मालिक"),
     PAN_CHAR_TO_LEGAL_STATUS["P"]),
]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\wऀ-ॣ०-ॿ']+", text.lower())


def _digit_string(tokens: list[str]) -> str:
    out, repeat = [], 1
    for tk in tokens:
        if tk in _REPEAT:
            repeat = _REPEAT[tk]
        elif tk.isdigit():
            out.append(tk)
            repeat = 1
        elif tk in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[tk] * repeat)
            repeat = 1
    return "".join(out)


def _clean_free_text(text: str) -> str:
    t = re.sub(r"[.,!?;:]+", " ", text).strip()
    t = _LEAD_FILLER.sub("", t)
    t = _TRAIL_FILLER.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def to_latin(text: str) -> str:
    """Devanagari -> Latin via Sarvam transliterate, so Hindi replies can be
    matched against the (Latin) city/state gazetteer. Falls back to the
    original text if the call fails."""
    if not re.search(r"[ऀ-ॿ]", text):
        return text
    try:
        r = requests.post(
            "https://api.sarvam.ai/transliterate", headers=_headers(), timeout=TIMEOUT,
            json={"input": text, "source_language_code": "hi-IN", "target_language_code": "en-IN"},
        )
        if r.status_code == 200:
            return r.json().get("transliterated_text") or text
    except (requests.RequestException, VoiceError):
        pass
    return text


def _best(text: str, choices, cutoff: int):
    hit = process.extractOne(text, list(choices), scorer=fuzz.WRatio, score_cutoff=cutoff, processor=str.lower)
    return hit[0] if hit else None


def _extract_value(key: str, text: str, engine, candidates=()) -> tuple[str | None, str]:
    """Return (value, note). value None = nothing usable heard."""
    tokens = _tokens(text)

    if key == "pincode":
        m = re.search(r"(?<!\d)[1-9]\d{5}(?!\d)", _digit_string(tokens))
        return (m.group(0), "") if m else (None, "I need a 6-digit pincode.")

    if key == "gstin":
        # speech arrives as "06BBEPS..." or spelled out ("zero six B B ...")
        parts = []
        for tk in _tokens(text):
            if tk in _REPEAT:
                continue
            parts.append(_DIGIT_WORDS.get(tk, tk))
        compact = re.sub(r"[^A-Za-z0-9]", "", "".join(parts)).upper()
        m = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", compact)
        if not m:
            return None, "GSTINs are hard to hear; please type it in the box below."
        if gstin_checksum_valid(m.group(0)):
            return m.group(0), ""
        return None, f"I heard {m.group(0)} but it fails the GSTIN check digit; please repeat or type it."

    cleaned = _clean_free_text(text)
    if not cleaned:
        return None, ""

    if key == "legal_status":
        low = cleaned.lower()
        for words, label in _LEGAL_KEYWORDS:
            if any(w in low for w in words):
                return label, ""
        return None, "Please say proprietorship, partnership, or private limited."

    if key == "state":
        latin = to_latin(cleaned)
        # values we already suspect beat the whole gazetteer, so a near-miss
        # resolves to the seller's own candidate, not a different real state
        found = _best(latin, candidates, 75) or _best(latin, engine.state_names, 80)
        return (found, "") if found else (None, "I did not recognise that state.")

    if key == "city":
        latin = to_latin(cleaned)
        hit = engine.city_matcher.match(latin)
        if hit:
            return hit["city"], ""
        found = _best(latin, candidates, 75) or _best(latin, engine.city_names, 85)
        if found:
            return found, ""
        return latin.title(), "Not found in the city list; kept as spoken."

    if key == "company_name":
        return (cleaned.title() if cleaned.islower() else cleaned), ""
    return cleaned, ""


def parse_reply(key: str, transcript: str, stage: str, engine, candidates=()) -> dict:
    """-> {"intent": yes|no|value|unclear, "value": str|None, "note": str}"""
    text = (transcript or "").strip()
    if not text:
        return {"intent": "unclear", "value": None, "note": "I did not catch that."}
    tokens = _tokens(text)
    has_yes = any(t in YES for t in tokens)
    has_no = any(t in NO for t in tokens)
    only_yn = bool(tokens) and all(t in YES or t in NO or t in POLITE for t in tokens)

    if stage == "confirm" and only_yn and (has_yes or has_no):
        # "no" anywhere wins ("yes... no, that's wrong")
        return {"intent": "no" if has_no else "yes", "value": None, "note": ""}

    value, note = _extract_value(key, text, engine, candidates)
    if value:
        return {"intent": "value", "value": value, "note": note}
    if stage == "confirm" and (has_yes or has_no):
        return {"intent": "no" if has_no else "yes", "value": None, "note": ""}
    return {"intent": "unclear", "value": None, "note": note or "I did not understand that."}
