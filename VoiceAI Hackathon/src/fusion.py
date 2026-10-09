"""
Core of the enrichment system: fuse a seller's raw KYC-document extractions
(already produced by IndiaMART's own document AI, see llm_extraction) into
one deduplicated, confidence-scored candidate profile.

Design principle: every field here is either
  (a) derived from the seller's own submitted documents (OCR/LLM extraction
      -> needs cross-validation, carries uncertainty), or
  (b) derived deterministically from public rules (the GSTIN numbering
      scheme) applied to a value from (a).
Nothing here reads the IndiaMART "answer key" tables -- those are only used
later, in validate.py, to score what this module produces.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from src import config
from src.address_parser import CityMatcher, extract_pincode
from src.gstin_rules import extract_gstin_signals

NAME_MATCH_THRESHOLD = 82  # rapidfuzz token_sort_ratio, 0-100


@dataclass
class FieldCandidate:
    value: str
    doc_type: str
    weight: float


@dataclass
class FusedField:
    value: str | None = None
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)
    all_candidates: list[dict] = field(default_factory=list)


def _cluster_candidates(
    candidates: list[FieldCandidate], exact: bool = False
) -> list[list[FieldCandidate]]:
    """Group matching string candidates.

    exact=False (default): fuzzy token-sort match, for names/addresses where
      OCR noise and case/spacing variants should collapse together
      (e.g. 'Shivay Enterprise' vs 'SHIVAY ENTERPRISES').
    exact=True: byte-for-byte match only. Required for identifiers like
      pincodes and GSTINs, where two values that merely *look* similar
      ('800007' vs '800001') are different codes, not OCR variants of the
      same one -- fuzzy clustering would wrongly merge them.
    """
    clusters: list[list[FieldCandidate]] = []
    for cand in candidates:
        placed = False
        for cluster in clusters:
            same = (
                cand.value.strip().lower() == cluster[0].value.strip().lower()
                if exact
                else fuzz.token_sort_ratio(cand.value.lower(), cluster[0].value.lower()) >= NAME_MATCH_THRESHOLD
            )
            if same:
                cluster.append(cand)
                placed = True
                break
        if not placed:
            clusters.append([cand])
    return clusters


def fuse_text_field(candidates: list[FieldCandidate], exact: bool = False) -> FusedField:
    """Weighted-vote fusion for a field. Use exact=True for identifiers
    (pincode, GSTIN) and leave exact=False (fuzzy) for names/addresses."""
    out = FusedField()
    candidates = [c for c in candidates if c.value and c.value.strip()]
    if not candidates:
        return out

    clusters = _cluster_candidates(candidates, exact=exact)
    clusters.sort(key=lambda cl: sum(c.weight for c in cl), reverse=True)
    winner = clusters[0]

    # representative value = longest string in the winning cluster
    # (tends to be the most complete / least truncated OCR read)
    winner_value = max(winner, key=lambda c: len(c.value)).value

    total_weight = sum(c.weight for cl in clusters for c in cl)
    winner_weight = sum(c.weight for c in winner)
    agreement_bonus = 0.15 * (len(winner) - 1)  # extra docs agreeing nudge confidence up
    confidence = min(1.0, (winner_weight / total_weight) * max(c.weight for c in winner) + agreement_bonus)

    out.value = winner_value
    out.confidence = round(confidence, 3)
    out.sources = sorted({c.doc_type for c in winner})
    out.all_candidates = [
        {"value": c.value, "doc_type": c.doc_type, "weight": c.weight} for c in candidates
    ]
    return out


def _add_address_text(buckets, text, doc_type, w, city_matcher: CityMatcher | None):
    """Record a raw address string, and (if a gazetteer is available) also
    derive city / state / pincode candidates from it."""
    if not text:
        return
    buckets["address_text"].append(FieldCandidate(text, doc_type, w))

    pin = extract_pincode(text)
    if pin:
        buckets["pincode"].append(FieldCandidate(pin, doc_type, w * 0.9))

    if city_matcher is not None:
        hit = city_matcher.match(text)
        if hit:
            buckets["city"].append(FieldCandidate(hit["city"], doc_type, w * 0.9))
            if hit.get("state"):
                buckets["state"].append(FieldCandidate(hit["state"], doc_type, w * 0.9))


def _collect_field_candidates(
    extracted_docs: list[dict], city_matcher: CityMatcher | None = None
) -> dict[str, list[FieldCandidate]]:
    """Walk every doc's llm_extraction JSON and pull out raw candidate values
    per logical field, tagged with a source-reliability weight."""
    buckets: dict[str, list[FieldCandidate]] = defaultdict(list)

    for doc in extracted_docs:
        doc_type = doc["doc_type"]
        ext = doc["extraction"] or {}
        w = config.SOURCE_WEIGHT.get(doc_type, 0.3)

        if doc_type == "Product Invoice":
            for name in ext.get("CompanyName") or []:
                buckets["company_name"].append(FieldCandidate(name, doc_type, w))
            for gst in ext.get("GST") or []:
                buckets["gstin"].append(FieldCandidate(gst, doc_type, w))
            for addr in ext.get("Address") or []:
                _add_address_text(buckets, addr, doc_type, w, city_matcher)
            for site in ext.get("Website") or []:
                buckets["website"].append(FieldCandidate(site, doc_type, w))
            for p in ext.get("Products") or []:
                if isinstance(p, dict) and p.get("name"):
                    buckets["products"].append(
                        FieldCandidate(
                            f"{p.get('name')}|{p.get('unit','')}|{p.get('price_per_unit','')}",
                            doc_type,
                            w,
                        )
                    )

        elif doc_type == "Sign Board":
            for name in ext.get("CompanyName") or []:
                buckets["company_name"].append(FieldCandidate(name, doc_type, w))
            for gst in ext.get("GST") or []:
                buckets["gstin"].append(FieldCandidate(gst, doc_type, w))
            for addr in ext.get("Address") or []:
                _add_address_text(buckets, addr, doc_type, w, city_matcher)

        elif doc_type == "Udhyam Certificate":
            udyam = ext.get("udyam_data") or {}
            names = udyam.get("parsed_names") or {}
            if names.get("trade_name"):
                buckets["company_name"].append(FieldCandidate(names["trade_name"], doc_type, w))
            elif udyam.get("enterprise_name"):
                buckets["company_name"].append(FieldCandidate(udyam["enterprise_name"], doc_type, w))
            if names.get("legal_name"):
                buckets["legal_name"].append(FieldCandidate(names["legal_name"], doc_type, w))

            addr = udyam.get("official_address") or {}
            if addr:
                parts = [
                    addr.get("flat_door_block", ""),
                    addr.get("premises_building", ""),
                    addr.get("road_street_lane", ""),
                    addr.get("village_town", ""),
                ]
                buckets["address_text"].append(
                    FieldCandidate(", ".join(p for p in parts if p), doc_type, w)
                )
                if addr.get("city"):
                    buckets["city"].append(FieldCandidate(addr["city"], doc_type, w))
                if addr.get("state"):
                    buckets["state"].append(FieldCandidate(addr["state"], doc_type, w))
                if addr.get("pincode"):
                    buckets["pincode"].append(FieldCandidate(str(addr["pincode"]), doc_type, w))

            if udyam.get("enterprise_type"):
                buckets["udyam_enterprise_type"].append(
                    FieldCandidate(udyam["enterprise_type"], doc_type, w)
                )
            for nic in udyam.get("nic_codes") or []:
                if isinstance(nic, dict) and nic.get("nic_5_digit"):
                    buckets["nic_activity"].append(
                        FieldCandidate(nic["nic_5_digit"], doc_type, w)
                    )

            gst_check = ext.get("gstin_verification") or {}
            if gst_check.get("provided_gstin"):
                buckets["gstin"].append(
                    FieldCandidate(gst_check["provided_gstin"], doc_type, w)
                )
            if gst_check.get("state_code_match") is False:
                buckets["risk_flags"].append(
                    FieldCandidate("udyam_gstin_state_mismatch", doc_type, w)
                )

        elif doc_type == "CANCELLED CHEQUE":
            acc = (ext.get("accholder_name") or {}).get("value") if isinstance(ext.get("accholder_name"), dict) else None
            if acc:
                buckets["company_name"].append(FieldCandidate(acc, doc_type, w))
            bank_addr = (ext.get("bank_address") or {}).get("value") if isinstance(ext.get("bank_address"), dict) else None
            if bank_addr:
                buckets["bank_address_text"].append(FieldCandidate(bank_addr, doc_type, w))
                # bank branch address is a weak locality signal, weight further reduced
                _add_address_text(buckets, bank_addr, doc_type, w * 0.4, city_matcher)

    return buckets


def build_seller_profile(
    seller_id: str, extracted_docs: list[dict], city_matcher: CityMatcher | None = None
) -> dict[str, Any]:
    """Fuse all of one seller's extracted documents into a single profile dict."""
    buckets = _collect_field_candidates(extracted_docs, city_matcher)

    company_name = fuse_text_field(buckets.get("company_name", []))
    gstin = fuse_text_field(buckets.get("gstin", []), exact=True)
    city = fuse_text_field(buckets.get("city", []))
    state = fuse_text_field(buckets.get("state", []))
    pincode = fuse_text_field(buckets.get("pincode", []), exact=True)
    address_text = fuse_text_field(buckets.get("address_text", []))
    nic_activity = fuse_text_field(buckets.get("nic_activity", []))
    udyam_enterprise_type = fuse_text_field(buckets.get("udyam_enterprise_type", []))

    # Legal status: deterministic rule from the extracted GSTIN's PAN
    # entity-type character, cross-checked against Udyam enterprise_type.
    legal_status = FusedField()
    gstin_signals = extract_gstin_signals(gstin.value) if gstin.value else {}
    if gstin_signals.get("legal_status"):
        legal_status.value = gstin_signals["legal_status"]
        legal_status.confidence = round(0.9 * gstin.confidence, 3) if gstin.confidence else 0.6
        legal_status.sources = ["gstin_pan_rule"]
        legal_status.all_candidates = [{"basis": "gstin_pan_char", "char": gstin_signals.get("pan_entity_char")}]

    # If GSTIN carries a state code and we don't already have a fused
    # `state`, fall back to the deterministic state-code table.
    if not state.value and gstin_signals.get("state_name"):
        state.value = gstin_signals["state_name"]
        state.confidence = 0.75
        state.sources = ["gstin_state_code"]

    risk_flags = sorted({c.value for c in buckets.get("risk_flags", [])})

    products = []
    seen = set()
    for c in buckets.get("products", []):
        if c.value not in seen:
            seen.add(c.value)
            name, unit, price = (c.value.split("|") + ["", ""])[:3]
            products.append({"name": name, "unit": unit, "price_per_unit": price, "source": c.doc_type})

    doc_types_seen = sorted({d["doc_type"] for d in extracted_docs})

    return {
        "seller_id": seller_id,
        "doc_count": len(extracted_docs),
        "doc_types_seen": doc_types_seen,
        "company_name": vars(company_name),
        "gstin": vars(gstin),
        "gstin_signals": gstin_signals,
        "legal_status": vars(legal_status),
        "address": {
            "city": vars(city),
            "state": vars(state),
            "pincode": vars(pincode),
            "raw_text": vars(address_text),
        },
        "nic_activity": vars(nic_activity),
        "udyam_enterprise_type": vars(udyam_enterprise_type),
        "products_mentioned": products,
        "risk_flags": risk_flags,
    }


def build_all_profiles(
    grouped_docs: dict[str, list[dict]], city_matcher: CityMatcher | None = None
) -> dict[str, dict]:
    return {
        sid: build_seller_profile(sid, docs, city_matcher)
        for sid, docs in grouped_docs.items()
    }
