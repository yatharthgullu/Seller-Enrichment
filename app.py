"""
Seller Enrichment -- demo UI.

Picks a seller, shows the fused/confidence-scored profile built purely from
their own KYC documents, lets you accept/edit each field, and (optionally)
shows IndiaMART's verified answer key side-by-side so the accuracy of the
pipeline is visible at a glance.

Run with:
    streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src import config, enrich as enr
from src.export import build_export_dataframe, flatten_profile

st.set_page_config(page_title="Seller Enrichment", layout="wide")

CORRECTIONS_FILE = config.OUTPUTS / "corrections.json"


# ----------------------------------------------------------------------------
# data loading (cached)
# ----------------------------------------------------------------------------

@st.cache_data
def load_outputs():
    with open(config.OUTPUTS / "enriched_profiles.json", encoding="utf-8") as f:
        enriched = json.load(f)
    with open(config.OUTPUTS / "metrics_summary.json", encoding="utf-8") as f:
        metrics = json.load(f)
    val_path = config.OUTPUTS / "validation_per_seller.json"
    validation = {}
    if val_path.exists():
        with open(val_path, encoding="utf-8") as f:
            validation = {r["seller_id"]: r for r in json.load(f)}
    return enriched, metrics, validation


@st.cache_data
def load_ground_truth():
    sellers = pd.read_csv(config.F_SELLERS, low_memory=False)
    sellers["fk_glusr_usr_id"] = sellers["fk_glusr_usr_id"].astype(str)
    cats = pd.read_csv(config.F_CATEGORIES, low_memory=False)
    cats["fk_glusr_usr_id"] = cats["fk_glusr_usr_id"].astype(str)
    return sellers.set_index("fk_glusr_usr_id"), cats


def load_corrections() -> dict:
    if CORRECTIONS_FILE.exists():
        with open(CORRECTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_correction(seller_id: str, field: str, old_value, new_value: str):
    data = load_corrections()
    data.setdefault(seller_id, {})[field] = {
        "old_value": old_value,
        "new_value": new_value,
    }
    with open(CORRECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ----------------------------------------------------------------------------
# small UI helpers
# ----------------------------------------------------------------------------

def confidence_badge(conf: float) -> str:
    if conf >= config.CONFIDENCE_HIGH:
        color, label = "#1a7f37", "high"
    elif conf >= config.CONFIDENCE_MED:
        color, label = "#9a6700", "medium"
    else:
        color, label = "#cf222e", "low"
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:10px;font-size:0.75em">{label} · {conf:.2f}</span>'


def field_row(label: str, field: dict, seller_id: str, field_key: str, show_truth=None):
    value = field.get("value") or "—"
    raw_conf = field.get("confidence", 0.0)
    calibrated = field.get("calibrated_confidence")
    conf = calibrated if calibrated is not None else raw_conf
    sources = ", ".join(field.get("sources", [])) or "no source"

    cols = st.columns([2, 3, 2, 2, 2])
    cols[0].markdown(f"**{label}**")
    cols[1].write(value)
    badge_html = confidence_badge(conf)
    if calibrated is not None:
        badge_html += f'<span style="color:#888;font-size:0.72em"> (raw {raw_conf:.2f})</span>'
    cols[2].markdown(badge_html, unsafe_allow_html=True)
    cols[3].caption(f"source: {sources}")

    if show_truth is not None:
        truth_str = str(show_truth) if show_truth not in (None, "nan") else "—"
        match = (
            str(value).strip().lower() == str(show_truth).strip().lower()
            if value != "—" and show_truth not in (None, "nan")
            else None
        )
        icon = "✅" if match else ("❌" if match is False else "·")
        cols[4].caption(f"answer key: {truth_str} {icon}")

    edit_key = f"edit_{seller_id}_{field_key}"
    with st.expander(f"edit / view candidates — {label}", expanded=False):
        new_val = st.text_input("corrected value", value=field.get("value") or "", key=edit_key)
        if st.button("save correction", key=f"save_{edit_key}"):
            save_correction(seller_id, field_key, field.get("value"), new_val)
            st.success("Correction logged.")
        candidates = field.get("all_candidates", [])
        if candidates:
            st.caption("all candidate values seen across documents:")
            st.table(pd.DataFrame(candidates))



# ----------------------------------------------------------------------------
# upload mode: bring your own sellers' documents -> triaged, editable profile
# ----------------------------------------------------------------------------

SAMPLE_DIR = config.ROOT / "data" / "samples"
BUCKET_STYLE = {
    "high": ("#1a7f37", "auto-fill"),
    "medium": ("#9a6700", "confirm"),
    "low": ("#cf222e", "review"),
    "missing": ("#6e7781", "fill in"),
    "verified": ("#0969da", "confirmed"),
}


@st.cache_resource(show_spinner="Loading gazetteer, taxonomy and calibration...")
def get_engine():
    return enr.load_engine()


def bucket_badge(bucket: str, conf) -> str:
    color, label = BUCKET_STYLE[bucket]
    score = f" · {conf:.2f}" if conf is not None else ""
    return (f'<span style="background:{color};color:white;padding:2px 8px;'
            f'border-radius:10px;font-size:0.75em">{label}{score}</span>')


def set_correction(seller_id: str, key: str, old_value, new_value: str):
    new_value = (new_value or "").strip()
    if not new_value:
        return
    st.session_state.setdefault("corrections", {}).setdefault(seller_id, {})[key] = {
        "old_value": old_value, "new_value": new_value,
    }
    save_correction(seller_id, key, old_value, new_value)  # audit trail on disk


def _save_typed(seller_id: str, key: str, old_value, widget_key: str):
    set_correction(seller_id, key, old_value, st.session_state.get(widget_key, ""))


def ingest(sources: list[tuple[str, bytes]]):
    """Parse + enrich uploaded files, keep the result in session state."""
    report = enr.ParseReport()
    grouped: dict[str, list[dict]] = {}
    for name, data in sources:
        for sid, docs in enr.parse_upload(name, data, report).items():
            grouped.setdefault(sid, []).extend(docs)
    if not grouped:
        raise ValueError("No usable documents found (need doc types: "
                         + ", ".join(sorted(config.EXTRACTABLE_DOC_TYPES)) + ").")
    bar = st.progress(0.0, text="Fusing documents...")
    results = enr.enrich(grouped, get_engine(), lambda i, n: bar.progress(i / n, text=f"Fusing {i}/{n} sellers"))
    bar.empty()
    st.session_state["up_results"] = results
    st.session_state["up_report"] = report
    st.session_state["corrections"] = {}


def render_upload_tab():
    st.subheader("Enrich sellers from their own documents")
    st.caption(
        "Upload one seller or many. Each field comes back pre-filled with a confidence "
        "score and a plain-English reason, sorted into **auto-fill** (high), **confirm** "
        "(medium) or **review / fill in** (low or missing), so people only touch what "
        "actually needs them. No answer key is used here."
    )

    left, right = st.columns([3, 2])
    files = left.file_uploader(
        "KYC documents with `llm_extraction` (CSV like so_kyc_documents.csv, or JSON)",
        type=["csv", "json"], accept_multiple_files=True,
    )
    with right:
        st.caption("No files handy?")
        use_sample = st.button("Load 8-seller sample")
        for fname, label in (("sample_upload_multi.csv", "multi-seller CSV"),
                             ("sample_upload_single.json", "single-seller JSON")):
            fpath = SAMPLE_DIR / fname
            if fpath.exists():
                st.download_button(f"Download {label}", fpath.read_bytes(), fname, key=f"dl_{fname}")

    sources = [(f.name, f.getvalue()) for f in files] if files else []
    if not sources and use_sample:
        sources = [("sample_upload_multi.csv", (SAMPLE_DIR / "sample_upload_multi.csv").read_bytes())]
    if sources:
        sig = hash(tuple((n, len(b), hash(b)) for n, b in sources))
        if st.session_state.get("up_sig") != sig:
            try:
                ingest(sources)
                st.session_state["up_sig"] = sig
            except Exception as e:  # malformed upload: tell the user, keep the app alive
                st.error(f"Could not read the upload: {e}")
                return

    results = st.session_state.get("up_results")
    if not results:
        st.info("Upload documents (or load the sample) to see predicted fields with confidence.")
        return

    report = st.session_state["up_report"]
    corrections = st.session_state.get("corrections", {})
    st.caption(
        f"Read {report.docs_read} documents for {len(results)} sellers"
        + (f" · skipped {report.docs_skipped_type} of an unsupported type" if report.docs_skipped_type else "")
        + (f" · skipped {report.docs_skipped_json} without valid extraction JSON" if report.docs_skipped_json else "")
    )

    triages = {sid: enr.triage_profile(e, corrections.get(sid)) for sid, e in results.items()}
    all_fields = [f for t in triages.values() for f in t["fields"]]
    n_auto = sum(f["bucket"] in ("high", "verified") for f in all_fields)
    m = st.columns(4)
    m[0].metric("Sellers", len(triages))
    m[1].metric("Fields auto-filled / confirmed", f"{n_auto / len(all_fields) * 100:.0f}%")
    m[2].metric("Sellers fully ready", sum(t["ready"] for t in triages.values()))
    m[3].metric("Fields needing a person", len(all_fields) - n_auto)

    overview = pd.DataFrame([
        {"seller": sid, "docs": results[sid]["profile"]["doc_count"],
         "status": "ready" if t["ready"] else f"{t['needs_attention']} to check",
         "check": ", ".join(f["key"] for f in t["fields"] if f["bucket"] in ("medium", "low", "missing"))}
        for sid, t in triages.items()
    ]).sort_values("status", key=lambda c: c == "ready", kind="stable")
    with st.expander("All sellers at a glance", expanded=len(triages) > 1):
        st.dataframe(overview, hide_index=True, width="stretch")

    seller_id = st.selectbox(
        "Seller", list(triages),  # stable order + key, or fixing a field would reset the pick
        key="up_seller",
        format_func=lambda s: f"{s}  ·  " + ("✅ ready" if triages[s]["ready"] else f"⚠ {triages[s]['needs_attention']} to check"),
    )
    entry, tri = results[seller_id], triages[seller_id]
    profile = entry["profile"]
    st.caption(f"Fused from {profile['doc_count']} documents: {', '.join(profile['doc_types_seen'])}")
    if tri["risk_flags"]:
        st.warning(f"Risk flags: {', '.join(tri['risk_flags'])}")

    for f in tri["fields"]:
        key = f["key"]
        c = st.columns([2, 3, 2, 3])
        c[0].markdown(f"**{f['label']}**")
        c[1].write(f["value"] or "—")
        c[1].caption(" · ".join(f["reasons"]))
        c[2].markdown(bucket_badge(f["bucket"], f["confidence"]), unsafe_allow_html=True)
        with c[3]:
            if f["bucket"] in ("medium", "low") and f["value"]:
                st.button("✓ Confirm", key=f"ok_{seller_id}_{key}",
                          on_click=set_correction, args=(seller_id, key, f["predicted_value"], f["value"]))
            # offer swap buttons only for real conflicts / a checksum-valid GSTIN;
            # a minor lower-trust disagreement is already explained in the reasons
            for i, alt in enumerate(f["alternatives"][:2] if (f["material_conflict"] or f["suggested"]) else []):
                st.button(f"Use '{alt}'", key=f"alt_{seller_id}_{key}_{i}",
                          on_click=set_correction, args=(seller_id, key, f["predicted_value"], alt))
            with st.expander("type a value"):
                wk = f"txt_{seller_id}_{key}"
                st.text_input("value", value=f["value"] or "", key=wk, label_visibility="collapsed")
                st.button("Save", key=f"save_{seller_id}_{key}",
                          on_click=_save_typed, args=(seller_id, key, f["predicted_value"], wk))

    st.markdown("#### Suggested categories")
    cats = entry["category_suggestions"]
    if cats:
        st.caption("Keyword-matched suggestions only (weakest signal in the pipeline); never auto-filled.")
        st.table(pd.DataFrame([{"category": c["category_name"], "group": c["group_name"],
                                "score": c["confidence"]} for c in cats]))
    else:
        st.caption("No category signal (no invoice products or NIC text in these documents).")

    st.markdown("---")
    export_df = pd.DataFrame([enr.triage_to_row(results[sid], triages[sid]) for sid in triages])
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ All sellers, values + confidence + status (CSV)",
                       export_df.to_csv(index=False).encode("utf-8"),
                       "enriched_sellers.csv", "text/csv")
    d2.download_button("⬇️ Full triage (JSON)",
                       json.dumps({sid: {"triage": triages[sid], "profile": results[sid]["profile"]}
                                   for sid in triages}, default=str).encode("utf-8"),
                       "enriched_sellers.json", "application/json")

# ----------------------------------------------------------------------------
# app
# ----------------------------------------------------------------------------

enriched, metrics, validation = load_outputs()
sellers_gt, cats_gt = load_ground_truth()

st.title("Seller Enrichment — non-IM documents → IndiaMART profile")
st.caption(
    "Fuses a seller's own KYC documents (invoice, sign board, Udyam certificate, cancelled cheque) "
    "into one confidence-scored profile, maps it to the IM category taxonomy, and backtests every "
    "field against IndiaMART's verified seller records."
)

tab_upload, tab_dashboard, tab_profile = st.tabs(
    ["📤 Enrich a seller (upload)", "📊 Dataset-level accuracy", "🔎 Seller profile"]
)

with tab_upload:
    render_upload_tab()

with tab_dashboard:
    st.subheader("Backtest results — 3,000 sellers, verified answer key")
    c = st.columns(4)
    c[0].metric("Company name match", f"{metrics['company_name_match_rate']['rate']*100:.1f}%",
                help=f"n={metrics['company_name_match_rate']['n']}, fuzzy match ≥80")
    c[1].metric("GSTIN entity-char match", f"{metrics['gstin_6th_char_match_rate']['rate']*100:.1f}%",
                help="validated via the privacy-safe gstin_num_6th_char field")
    c[2].metric("Legal status match", f"{metrics['legal_status_match_rate']['rate']*100:.1f}%",
                help="derived deterministically from the GSTIN's PAN entity-type character")
    c[3].metric("Field coverage", f"{metrics['field_coverage_rate']*100:.1f}%",
                help=f"avg {metrics['avg_fields_populated']}/{metrics['fields_total_per_seller']} fields auto-filled")

    c2 = st.columns(4)
    c2[0].metric("City match", f"{metrics['city_match_rate']['rate']*100:.1f}%")
    c2[1].metric("State match", f"{metrics['state_match_rate']['rate']*100:.1f}%")
    c2[2].metric("Pincode match", f"{metrics['pincode_match_rate']['rate']*100:.1f}%")
    c2[3].metric("Category top-5 precision", f"{metrics['category_top5_precision']['avg']*100:.1f}%",
                 help=f"n={metrics['category_top5_precision']['n']} sellers with ≥1 category suggestion")

    st.markdown("---")
    st.markdown(
        f"**Catalog-health bonus:** {metrics['catalog_health_bonus']['sellers_with_catalog_gaps_and_invoice_products']} "
        f"sellers with catalogue gaps (missing price/specs) had invoice-extracted products that could auto-fill them "
        f"({metrics['catalog_health_bonus']['products_price_fillable']} priced line items recovered)."
    )
    with st.expander("full raw metrics JSON"):
        st.json(metrics)

    st.markdown("---")
    st.subheader("Download predicted data")
    st.caption(
        "Every field alongside its confidence score — apply your own confidence "
        "threshold downstream to decide what gets auto-accepted vs. routed for review."
    )
    export_df = build_export_dataframe(enriched)
    # only fields that were independently backtested against the answer key
    # get a calibrated score and belong in the "is this profile trustworthy"
    # gate. GSTIN has no independent ground-truth check (we only validate its
    # 6th character, not the full number) so it's excluded here and shown
    # separately -- folding its structurally-lower raw score in would make
    # almost every seller fail the strict gate for a reason unrelated to
    # whether the *validated* fields are actually reliable.
    calibrated_cols = [
        "company_name_confidence", "legal_status_confidence",
        "city_confidence", "state_confidence", "pincode_confidence",
    ]
    st.caption(
        "Confidence values below are **calibrated**: the fusion engine's raw score "
        "(source weight + cross-document agreement) ranks fields correctly but runs "
        "conservative on an absolute scale — a raw 0.55 was still right ~85% of the "
        "time in the backtest. We fit a bin-wise mapping from raw confidence → "
        "empirical accuracy (see `outputs/confidence_calibration.json`) so a threshold "
        "here means what it says. The auto-accept gate below covers only the 5 "
        "independently-validated fields; GSTIN has no full-number ground truth to "
        "calibrate against, so it's tracked separately (raw score, in the export)."
    )
    threshold = st.slider(
        "Confidence threshold for auto-accept",
        0.0, 1.0, config.CONFIDENCE_HIGH, 0.05,
    )
    # a missing field (NaN) is NOT a pass -- no prediction is worse than a
    # low-confidence one, so it must count as "needs review", not be
    # excused from the check.
    passes = export_df[calibrated_cols].fillna(-1) >= threshold

    st.caption(
        "Two views of the same threshold: per-**field** (how a real system would "
        "actually auto-accept — field by field) and per-**seller** (the strict bar "
        "of every single field passing before touching nothing for that seller)."
    )
    c1, c2, c3 = st.columns(3)
    field_pass_rate = passes.values.mean()
    c1.metric("Fields auto-acceptable at this threshold", f"{field_pass_rate*100:.1f}%",
              help="share of all (seller, field) cells with confidence ≥ threshold")
    c2.metric("Sellers with ALL fields above threshold", int(passes.all(axis=1).sum()),
              help="strict bar: zero fields need review for this seller")
    c3.metric("Sellers needing ≥1 field reviewed", int((~passes.all(axis=1)).sum()))

    dl_col1, dl_col2 = st.columns(2)
    dl_col1.download_button(
        "⬇️ Download all predictions + confidence (CSV)",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name="seller_enrichment_predictions.csv",
        mime="text/csv",
    )
    dl_col2.download_button(
        "⬇️ Download full fused profiles (JSON, all sellers)",
        data=json.dumps(enriched, default=str).encode("utf-8"),
        file_name="seller_enrichment_profiles_full.json",
        mime="application/json",
    )
    with st.expander("preview export table"):
        st.dataframe(export_df.head(50))

with tab_profile:
    all_ids = sorted(enriched.keys())
    # surface a few interesting sellers first (multi-doc, high confidence)
    interesting = sorted(
        all_ids, key=lambda sid: enriched[sid]["profile"]["doc_count"], reverse=True
    )[:25]
    seller_id = st.selectbox(
        "Pick a seller (GLID)",
        options=all_ids,
        index=all_ids.index(interesting[0]) if interesting else 0,
    )
    show_truth = st.checkbox("Show IndiaMART verified answer key side-by-side", value=True)

    entry = enriched[seller_id]
    profile = entry["profile"]
    cat_suggestions = entry["category_suggestions"]
    truth_row = sellers_gt.loc[seller_id].to_dict() if seller_id in sellers_gt.index else {}

    st.subheader(f"Seller {seller_id}")
    st.caption(
        f"Fused from {profile['doc_count']} documents: {', '.join(profile['doc_types_seen'])}"
    )

    if profile["risk_flags"]:
        st.warning(f"Risk flags: {', '.join(profile['risk_flags'])}")

    st.markdown("#### Company identity")
    field_row("Company / trade name", profile["company_name"], seller_id, "company_name",
               show_truth=truth_row.get("company_name") if show_truth else None)
    field_row("GSTIN", profile["gstin"], seller_id, "gstin")
    field_row("Legal status", profile["legal_status"], seller_id, "legal_status",
               show_truth=truth_row.get("legal_status") if show_truth else None)

    st.markdown("#### Location")
    field_row("City", profile["address"]["city"], seller_id, "city",
               show_truth=truth_row.get("city_name") if show_truth else None)
    field_row("State", profile["address"]["state"], seller_id, "state",
               show_truth=truth_row.get("state_name") if show_truth else None)
    field_row("Pincode", profile["address"]["pincode"], seller_id, "pincode",
               show_truth=truth_row.get("pincode") if show_truth else None)
    if profile["address"]["raw_text"]["value"]:
        st.caption(f"raw address text: _{profile['address']['raw_text']['value']}_")

    st.markdown("#### People / roles — via GST registry lookup")
    st.info(
        "Owner/partner names and designation are not probabilistically extracted: once the GSTIN above "
        "is resolved, these come from an authoritative GST lookup, shown here as the verified record."
    )
    gst_names = truth_row.get("gst_partner_names")
    designation = truth_row.get("contact_designation")
    cols = st.columns(2)
    cols[0].write(f"**Partner/owner name(s):** {gst_names if pd.notna(gst_names) else '—'}")
    cols[1].write(f"**Designation:** {designation if pd.notna(designation) else '—'}")

    st.markdown("#### Suggested categories")
    if cat_suggestions:
        true_cats = set(
            cats_gt[cats_gt["fk_glusr_usr_id"] == seller_id]["category_name"].tolist()
        )
        rows = []
        for c in cat_suggestions:
            rows.append(
                {
                    "category": c["category_name"],
                    "group": c["group_name"],
                    "confidence": c["confidence"],
                    "in seller's real categories?": "✅" if c["category_name"] in true_cats else "·",
                }
            )
        st.table(pd.DataFrame(rows))
    else:
        st.caption("No category signal available for this seller (no invoice products / NIC text extracted).")

    if profile["products_mentioned"]:
        st.markdown("#### Products seen on invoices")
        st.table(pd.DataFrame(profile["products_mentioned"]))

    st.download_button(
        f"⬇️ Download this seller's profile (JSON)",
        data=json.dumps(entry, default=str, indent=2).encode("utf-8"),
        file_name=f"seller_{seller_id}_profile.json",
        mime="application/json",
    )

    with st.expander("full fused profile JSON"):
        st.json(profile)
