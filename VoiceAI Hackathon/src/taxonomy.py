"""
Map free-text signals (invoice product names, Udyam NIC activity
descriptions) onto IndiaMART's live category taxonomy.

Matches at the `category_name` level (696 distinct categories) rather than
the full 106,619-row MCAT level: coarse text match against 696 well-formed
category labels is far more reliable than against ~107k narrow MCAT names,
and `category_name` is exactly what so_seller_categories.csv carries, so the
result is directly scoreable against ground truth.

Approach: a cheap inverted-index + rapidfuzz re-rank, not embeddings --
keeps this dependency-light and fast enough to run on 3,000 sellers in a
hackathon's time budget without a vector DB or network calls.
"""
from __future__ import annotations

import re
from collections import defaultdict

import pandas as pd
from rapidfuzz import fuzz

STOPWORDS = {
    "and", "of", "for", "the", "in", "on", "a", "an", "to", "with", "&",
    "or", "other", "others", "items", "item", "products", "product",
}
TOKEN_RE = re.compile(r"[a-zA-Z]{3,}")


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    return {t.lower() for t in TOKEN_RE.findall(text)} - STOPWORDS


def _stem(tok: str) -> str:
    """Trivial plural-stripping stemmer: 'flavours' -> 'flavour'. Good enough
    to bridge singular/plural mismatches between free text and category
    labels without pulling in a real NLP stemmer dependency."""
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith("es") and tok[-3] in "sxz":
        return tok[:-2]
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


class CategoryMapper:
    def __init__(self, taxonomy_df: pd.DataFrame):
        cats = taxonomy_df[["category_id", "category_name", "group_name"]].dropna(
            subset=["category_id", "category_name"]
        ).drop_duplicates(subset="category_id")
        self.categories = cats.set_index("category_id")[["category_name", "group_name"]].to_dict("index")

        self.index: dict[str, set[int]] = defaultdict(set)
        self._cat_stems: dict[int, set[str]] = {}
        for cat_id, name in cats.set_index("category_id")["category_name"].items():
            stems = {_stem(t) for t in _tokenize(name)}
            self._cat_stems[cat_id] = stems
            for stem in stems:
                self.index[stem].add(cat_id)

    def suggest(self, text: str, top_k: int = 5) -> list[dict]:
        tokens = _tokenize(text)
        if not tokens:
            return []
        stems = {_stem(t) for t in tokens}

        candidate_ids: set[int] = set()
        for stem in stems:
            candidate_ids |= self.index.get(stem, set())
        if not candidate_ids:
            return []

        scored = []
        for cat_id in candidate_ids:
            info = self.categories[cat_id]
            cat_stems = self._cat_stems[cat_id]

            # fraction of query stems found (exact, or fuzzy near-miss) in
            # the category's stem set -- robust to length mismatch between
            # a short product name and a long, descriptive category label
            matched = 0.0
            for s in stems:
                if s in cat_stems:
                    matched += 1
                elif any(fuzz.ratio(s, cs) >= 85 for cs in cat_stems):
                    matched += 0.7
            overlap = matched / len(stems)
            tiebreak = fuzz.partial_ratio(text, info["category_name"]) / 100
            score = round(0.85 * overlap + 0.15 * tiebreak, 3)

            scored.append(
                {
                    "category_id": cat_id,
                    "category_name": info["category_name"],
                    "group_name": info["group_name"],
                    "score": score,
                }
            )
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]

    def suggest_for_profile(self, profile: dict, top_k: int = 5) -> list[dict]:
        """Combine every text signal in a fused profile into one bag and
        rank candidate categories by how many distinct signals support each
        one plus the best textual match score -- gives products *and* the
        Udyam NIC description a vote rather than just concatenating text."""
        signals = []
        nic = profile.get("nic_activity", {}).get("value")
        if nic:
            signals.append(nic)
        for p in profile.get("products_mentioned", []):
            if p.get("name"):
                signals.append(p["name"])

        if not signals:
            return []

        tally: dict[int, dict] = {}
        for sig in signals:
            for hit in self.suggest(sig, top_k=3):
                cid = hit["category_id"]
                if cid not in tally:
                    tally[cid] = {**hit, "support": 0, "best_score": hit["score"]}
                tally[cid]["support"] += 1
                tally[cid]["best_score"] = max(tally[cid]["best_score"], hit["score"])

        ranked = sorted(
            tally.values(),
            key=lambda d: (d["support"], d["best_score"]),
            reverse=True,
        )
        for r in ranked:
            r["confidence"] = round(min(1.0, 0.5 * r["best_score"] + 0.15 * r["support"]), 3)
        return ranked[:top_k]
