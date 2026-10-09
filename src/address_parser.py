"""
Light-weight address parsing for the free-text `Address` strings that come
out of invoice / sign-board OCR (e.g. "... CAUSEWAY ROAD, SINGANPORE
CHARRASTA, SURAT 395004, Gujarat, India").

Deliberately NOT using the seller answer-key tables as a lookup source --
that would be circular (scoring a field against the same table used to
produce it). Instead this matches against the public IndiaMART city/state
gazetteer (`ref_cities.csv` / `ref_states.csv`), the same kind of reference
data a production geocoder would use.
"""
from __future__ import annotations

import re

import pandas as pd

PINCODE_RE = re.compile(r"\b([1-9][0-9]{5})\b")


class CityMatcher:
    def __init__(self, cities_df: pd.DataFrame, states_df: pd.DataFrame):
        states_by_id = states_df.set_index("gl_state_id")["gl_state_name"].to_dict()

        entries = []
        for row in cities_df.itertuples(index=False):
            name = getattr(row, "gl_city_name")
            if not isinstance(name, str) or len(name) < 4:
                continue
            state_id = getattr(row, "fk_gl_state_id")
            entries.append(
                {
                    "city": name,
                    "city_id": getattr(row, "gl_city_id"),
                    "state": states_by_id.get(state_id),
                    "pattern": re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE),
                }
            )
        # longest names first so "New Delhi" is tried before "Delhi"
        entries.sort(key=lambda e: len(e["city"]), reverse=True)
        self.entries = entries

    def match(self, text: str) -> dict | None:
        if not text:
            return None
        for e in self.entries:
            if e["pattern"].search(text):
                return {"city": e["city"], "city_id": e["city_id"], "state": e["state"]}
        return None


def extract_pincode(text: str) -> str | None:
    if not text:
        return None
    m = PINCODE_RE.search(text)
    return m.group(1) if m else None
