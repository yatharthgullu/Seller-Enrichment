"""
Deterministic rules derived from the public GSTIN numbering scheme.

GSTIN layout (15 chars): SS PPPPPPPPPP E Z C
  SS = 2-digit state code (positions 1-2)
  PPPPPPPPPP = 10-char PAN (positions 3-12)
    - PAN's own 4th character (= GSTIN position 6) encodes the holder's
      legal-entity type. This is exactly what the dataset's
      `gstin_num_6th_char` field captures.
  E = entity/registration number under the same PAN (position 13)
  Z = fixed literal 'Z' (position 14)
  C = checksum (position 15)

Both tables below are public knowledge (CBIC / Income Tax PAN structure),
not derived from the dataset. They let the pipeline turn a raw GSTIN,
extracted from a document, into a state and a legal-entity-type signal
without needing any external lookup.
"""

# position 1-2 -> state name, as used by so_sellers.state_name
GST_STATE_CODE = {
    "01": "Jammu And Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman And Diu", "26": "Dadra And Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (Old)", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman And Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}

# PAN 4th char (= GSTIN 6th char) -> legal entity type, mapped onto this
# dataset's ref_legal_status.csv ids/labels
PAN_CHAR_TO_LEGAL_STATUS = {
    "P": "Individual - Proprietor",
    "C": "Limited Company (Ltd./Pvt.Ltd.)",
    "H": "HUF Firm (Hindu Undivided Family)",
    "F": "Partnership Firm",
    "A": "Association of Person",
    "T": "Trust / Association of Person / Body of Individual",
    "B": "Body of Individual",
    "L": "Government Firm / Local Authority / Artificial Judiciary",
    "J": "Artificial Judiciary Person",
    "G": "Government Firm / Local Authority / Artificial Judiciary",
}


def extract_gstin_signals(gstin: str) -> dict:
    """Pull state + legal-status hints out of a raw GSTIN string.

    Returns {} if the string doesn't look like a 15-char GSTIN.
    """
    if not gstin:
        return {}
    gstin = gstin.strip().upper()
    if len(gstin) != 15:
        return {}
    state_code = gstin[0:2]
    pan_char = gstin[5]  # 6th character, 0-indexed position 5
    out = {"gstin": gstin, "state_code": state_code, "pan_entity_char": pan_char}
    if state_code in GST_STATE_CODE:
        out["state_name"] = GST_STATE_CODE[state_code]
    if pan_char in PAN_CHAR_TO_LEGAL_STATUS:
        out["legal_status"] = PAN_CHAR_TO_LEGAL_STATUS[pan_char]
    return out


def sixth_char_matches(gstin: str, gstin_num_6th_char) -> bool | None:
    """Validate an extracted GSTIN against the dataset's privacy-safe
    `gstin_num_6th_char` ground-truth field. Returns None if not comparable.
    """
    if not gstin or not isinstance(gstin_num_6th_char, str) or not gstin_num_6th_char.strip():
        return None
    gstin = gstin.strip().upper()
    if len(gstin) != 15:
        return None
    return gstin[5] == gstin_num_6th_char.strip().upper()
