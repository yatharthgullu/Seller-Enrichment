"""Fusion: clustering, weighted vote and the confidence formula."""
import pytest

from src import config
from src.fusion import FieldCandidate, build_seller_profile, fuse_text_field


def cand(value, doc_type):
    return FieldCandidate(value, doc_type, config.SOURCE_WEIGHT[doc_type])


def test_empty_and_blank_candidates_give_no_value():
    out = fuse_text_field([cand("   ", "Sign Board")])
    assert out.value is None and out.confidence == 0.0


def test_fuzzy_cluster_merges_spelling_variants():
    out = fuse_text_field([cand("Shivay Enterprise", "Sign Board"),
                           cand("SHIVAY ENTERPRISES", "Product Invoice")])
    assert len(out.sources) == 2  # both documents landed in the winning cluster


def test_exact_mode_does_not_merge_near_miss_identifiers():
    out = fuse_text_field([cand("800007", "Product Invoice"),
                           cand("800001", "Sign Board")], exact=True)
    assert out.sources == ["Product Invoice"]  # higher weight wins alone
    assert out.value == "800007"


def test_weighted_vote_matches_documented_example():
    # Two weaker sources agree and outvote the invoice's misread.
    out = fuse_text_field([cand("DEV ENTERPRISE", "CANCELLED CHEQUE"),
                           cand("DEV ENTERPRISE", "Sign Board"),
                           cand("DEV DENTERPRISE", "Product Invoice")])
    assert out.value == "DEV ENTERPRISE"
    assert out.sources == ["CANCELLED CHEQUE", "Sign Board"]
    # share 1.00/1.65 x strongest 0.55 + 0.15 agreement bonus
    assert out.confidence == pytest.approx(0.483, abs=1e-3)


def test_single_source_confidence_is_its_weight():
    out = fuse_text_field([cand("ABC TRADERS", "Udhyam Certificate")])
    assert out.confidence == pytest.approx(config.SOURCE_WEIGHT["Udhyam Certificate"])


def test_confidence_is_capped_at_one():
    docs = ["Udhyam Certificate", "Product Invoice", "Sign Board", "CANCELLED CHEQUE"]
    out = fuse_text_field([cand("ABC TRADERS", d) for d in docs])
    assert out.confidence == 1.0


def test_longest_spelling_is_displayed():
    out = fuse_text_field([cand("ABC TRADERS", "Sign Board"),
                           cand("ABC TRADERS LTD", "Product Invoice")])
    assert out.sources == ["Product Invoice", "Sign Board"]  # merged (fuzzy 84.6)
    assert out.value == "ABC TRADERS LTD"  # the less truncated read is shown


def test_known_limitation_pvt_ltd_suffix_splits_cluster():
    # token-sort ratio is 73 < 82, so a long legal suffix keeps the two apart.
    # Listed as a known limitation; this pins the current behaviour.
    out = fuse_text_field([cand("ABC TRADERS", "Sign Board"),
                           cand("ABC TRADERS PVT LTD", "Product Invoice")])
    assert len(out.sources) == 1


def test_profile_derives_legal_status_and_state_from_gstin():
    docs = [{"doc_type": "Product Invoice",
             "extraction": {"CompanyName": ["ABC TRADERS"], "GST": ["27AAPFU0939F1ZV"]}}]
    prof = build_seller_profile("S1", docs)
    assert prof["gstin"]["value"] == "27AAPFU0939F1ZV"
    assert prof["legal_status"]["value"] == "Partnership Firm"
    assert prof["legal_status"]["sources"] == ["gstin_pan_rule"]
    assert prof["address"]["state"]["value"] == "Maharashtra"
    assert prof["address"]["state"]["sources"] == ["gstin_state_code"]


def test_profile_flags_udyam_gstin_state_mismatch():
    docs = [{"doc_type": "Udhyam Certificate",
             "extraction": {"gstin_verification": {"provided_gstin": "27AAPFU0939F1ZV",
                                                   "state_code_match": False}}}]
    prof = build_seller_profile("S2", docs)
    assert "udyam_gstin_state_mismatch" in prof["risk_flags"]
