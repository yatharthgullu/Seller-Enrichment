"""GSTIN rules: state code, PAN entity character, check digit."""
from src.gstin_rules import extract_gstin_signals, gstin_checksum_valid, sixth_char_matches

# 27AAPFU0939F1ZV is a publicly documented sample GSTIN with a valid check digit.
VALID = "27AAPFU0939F1ZV"


def test_checksum_accepts_valid_gstin():
    assert gstin_checksum_valid(VALID) is True


def test_checksum_is_case_and_whitespace_insensitive():
    assert gstin_checksum_valid(f"  {VALID.lower()} ") is True


def test_checksum_rejects_single_character_misread():
    misread = VALID[:-1] + "W"
    assert gstin_checksum_valid(misread) is False


def test_checksum_none_for_malformed_input():
    # None (not False) lets callers tell "not a GSTIN" apart from "OCR misread"
    assert gstin_checksum_valid("") is None
    assert gstin_checksum_valid("NOTAGSTIN") is None
    assert gstin_checksum_valid(VALID[:10]) is None


def test_signals_state_and_legal_status():
    sig = extract_gstin_signals(VALID)
    assert sig["state_code"] == "27"
    assert sig["state_name"] == "Maharashtra"
    assert sig["pan_entity_char"] == "F"
    assert sig["legal_status"] == "Partnership Firm"


def test_signals_empty_for_wrong_length():
    assert extract_gstin_signals("27AAPFU0939F1Z") == {}
    assert extract_gstin_signals("") == {}


def test_sixth_char_comparison():
    assert sixth_char_matches(VALID, "F") is True
    assert sixth_char_matches(VALID, "f") is True
    assert sixth_char_matches(VALID, "P") is False
    assert sixth_char_matches(VALID, "") is None
    assert sixth_char_matches("short", "F") is None
