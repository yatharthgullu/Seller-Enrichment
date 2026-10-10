"""
Builds the 10-seller test dataset in sample_data/.

    python scripts/make_sample_dataset.py            # write the files
    python scripts/make_sample_dataset.py --check    # also run each seller through the
                                                     # real engine and compare with the
                                                     # scenario it is meant to demonstrate

Everything here is fictional: business names, GLIDs (9001000xx), PANs and addresses. GSTINs are
well-formed with a correct check digit, so the validator treats them like real ones. Each seller is
designed to land in a different place in the triage, so the whole flow (auto-fill, confirm, collect,
phone call, apply) can be tested from one upload.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _sample_readme import README_BOTTOM, README_TOP  # noqa: E402

OUT = ROOT / "sample_data"
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ----------------------------------------------------------------------------
# GSTIN with a correct check digit (public base-36 weighted algorithm)
# ----------------------------------------------------------------------------

def gstin(state_code: str, pan: str) -> str:
    body = f"{state_code}{pan}1Z"
    total = 0
    for i, ch in enumerate(body):
        prod = ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return body + ALPHABET[(36 - total % 36) % 36]


def misread(g: str) -> str:
    """One OCR-style character error in the PAN part, so the check digit no longer matches."""
    swap = {"S": "5", "5": "S", "B": "8", "8": "B", "O": "0", "0": "O", "I": "1", "1": "I", "Z": "2", "2": "Z"}
    for i in range(2, 12):
        if g[i] in swap:
            return g[:i] + swap[g[i]] + g[i + 1:]
    return g[:5] + ("A" if g[5] != "A" else "B") + g[6:]


# ----------------------------------------------------------------------------
# the four document types the engine reads (the shapes match so_kyc_documents.csv)
# ----------------------------------------------------------------------------

def invoice(company, gst, address, products=None, customer="Sample Buyer Pvt Ltd"):
    return "Product Invoice", {
        "GST": [gst] if gst else [],
        "Reason": "Tax invoice with supplier details, a billing table and a grand total.",
        "Address": [address] if address else [],
        "Website": [],
        "Products": products or [],
        "isEnglish": "yes",
        "isInvoice": "yes",
        "CompanyName": [company] if company else [],
        "TotalAmount": 48250,
        "CustomerDetails": {"name": customer, "gstin": "", "address": ""},
    }


def sign_board(company, address=None, gst=None):
    return "Sign Board", {
        "GST": [gst] if gst else [],
        "Reason": ["Extraction focused on the main sign board."],
        "Aadhaar": [],
        "Address": [address] if address else [],
        "Website": [],
        "Services": [],
        "isEnglish": ["yes"],
        "CompanyName": [company] if company else [],
        "Designation": [],
        "SocialMedia": [],
        "isSignboard": ["yes"],
        "ProprietorName": [],
        "OperationalHours": [],
        "BankAccountDetails": [],
    }


def cheque(account_holder, bank_address="", bank="State Bank Of India"):
    return "CANCELLED CHEQUE", {
        "amount": {"value": ""},
        "bank_name": {"value": bank},
        "ifsc_code": {"value": "SBIN0000000"},
        "bank_branch": {"value": "MAIN BRANCH"},
        "bank_address": {"value": bank_address},
        "cheque_number": {"value": "000123"},
        "accholder_name": {"value": account_holder},
        "account_number": {"value": "XXXXXXXX4821"},
    }


def udyam(trade_name, city, state, pincode, gst=None, state_code_ok=True, enterprise_type="Micro",
          street="Main Road", building="Industrial Estate"):
    ext = {
        "udyam_data": {
            "units": [trade_name],
            "nic_codes": [{"nic_5_digit": "28299 - Manufacture of other special-purpose machinery n.e.c.",
                           "activity_type": "Manufacturing"}],
            "parsed_names": {"legal_name": "", "trade_name": trade_name},
            "major_activity": "MANUFACTURING",
            "enterprise_name": trade_name,
            "enterprise_type": enterprise_type,
            "official_address": {"city": city, "block": "", "state": state, "pincode": pincode, "district": city,
                                 "village_town": building, "flat_door_block": "12", "road_street_lane": street,
                                 "premises_building": building},
            "registration_number": "UDYAM-XX-00-0000000",
        },
    }
    if gst:
        ext["gstin_verification"] = {"provided_gstin": gst, "state_code_match": state_code_ok,
                                     "verification_status": "PASS" if state_code_ok else "FAIL"}
    return "Udhyam Certificate", ext


def product(name, unit="Nos", price=250):
    return {"name": name, "unit": unit, "price_per_unit": price}


# ----------------------------------------------------------------------------
# the 10 sellers
#   expect = what the triage should say: fields to confirm / collect, and whether it is ready
# ----------------------------------------------------------------------------

def sellers():
    S = []

    def add(glid, title, note, docs, confirm, collect):
        S.append({"glid": glid, "title": title, "note": note, "docs": docs, "confirm": confirm, "collect": collect})

    # 1. everything agrees across four documents ----------------------------------------------
    g = gstin("27", "AKRPS4821M")
    add("900100001", "Complete profile, nothing to do",
        "Four documents agree on every field. All six fields are auto-filled; no call is needed.",
        [udyam("SHREE GANESH FABRICATORS", "PUNE", "MAHARASHTRA", "411019", g),
         invoice("SHREE GANESH FABRICATORS", g, "Plot 14, MIDC Bhosari, Pune 411019 Maharashtra",
                 [product("MS Angle 40x40", "Kg", 68), product("Fabricated Frame", "Nos", 1850)]),
         sign_board("SHREE GANESH FABRICATORS", "Plot 14, MIDC Bhosari, Pune 411019"),
         cheque("SHREE GANESH FABRICATORS", "Bhosari Branch, Pune 411039 Maharashtra")],
        [], [])

    # 2. complete, a Pvt Ltd company -------------------------------------------------------------
    g = gstin("08", "AAQCM7310K")
    add("900100002", "Complete profile (private limited company)",
        "Udyam, invoice and sign board agree. Legal status is derived from the GSTIN (entity char 'C').",
        [udyam("MARUDHAR POLYMERS PRIVATE LIMITED", "JAIPUR", "RAJASTHAN", "302013", g, enterprise_type="Small"),
         invoice("MARUDHAR POLYMERS PRIVATE LIMITED", g, "D-22 VKI Area, Jaipur 302013 Rajasthan",
                 [product("HDPE Granules", "Kg", 112)]),
         sign_board("MARUDHAR POLYMERS PRIVATE LIMITED", "D-22 VKI Area, Jaipur 302013")],
        [], [])

    # 3. two fields to confirm, nothing to collect ----------------------------------------------
    g = gstin("03", "BLTPK2290D")
    add("900100003", "2 to confirm, 0 to collect",
        "The three documents spell the business differently and only the sign board gives a pincode "
        "(one weak source). The agent reads those two values back.",
        [invoice("GILL ENGINEERING WORKS", g, "Focal Point Phase 5, Ludhiana, Punjab",
                 [product("Gear Shaft", "Nos", 940)]),
         sign_board("GILL ENGG WORKS", "Focal Point, Ludhiana 141010", g),
         cheque("GILL ENGINEERING & CO", "Focal Point Branch, Ludhiana")],
        ["company_name", "pincode"], [])

    # 4. two to confirm, one to collect ----------------------------------------------------------
    g = gstin("24", "CMPPP5503E")
    add("900100004", "2 to confirm, 1 to collect",
        "No document carries a pincode (collect). The GSTIN appears on one document only, so the legal status "
        "derived from it is a confirm, and the company name is only half-agreed (confirm).",
        [invoice("PATEL AGRO TRADERS", g, "Station Road, Surat, Gujarat", [product("Cotton Seed", "Kg", 540)]),
         cheque("PATEL AGRO", "Ring Road Branch, Surat")],
        ["company_name", "legal_status"], ["pincode"])

    # 5. one to confirm, two to collect ----------------------------------------------------------
    g = gstin("33", "DNRPV8842H")
    add("900100005", "1 to confirm, 2 to collect",
        "The invoice has a name and GSTIN but an address with no city or pincode, so city and pincode are "
        "collected. Legal status is derived from a GSTIN seen once, so it is confirmed.",
        [invoice("VELAN ELECTRICALS", g, "No. 7, Gandhi Road", [product("Copper Wire 2.5mm", "Roll", 3200)]),
         sign_board("VELAN ELECTRICALS")],
        ["legal_status"], ["city", "pincode"])

    # 6. mostly collect ---------------------------------------------------------------------------
    add("900100006", "Sparse: cheque only",
        "Only a cancelled cheque was uploaded. Its account-holder name and bank address are weak signals "
        "(company, city and state are confirmed); GSTIN, legal status and pincode are missing and collected.",
        [cheque("SOMANI HANDLOOMS", "Kothari Marg Branch, Indore")],
        ["company_name", "city", "state"], ["gstin", "legal_status", "pincode"])

    # 7. GSTIN misread ---------------------------------------------------------------------------
    g = gstin("09", "EHDPS3317J")
    add("900100007", "GSTIN misread by OCR",
        "The invoice's GSTIN fails its check digit; the sign board's reading passes. The app suggests the valid "
        "one and lowers confidence on legal status, which is derived from it.",
        [invoice("AWADH FOOD PRODUCTS", misread(g), "Aminabad Road, Lucknow 226018 Uttar Pradesh",
                 [product("Basmati Rice 25kg", "Bag", 1800)]),
         sign_board("AWADH FOOD PRODUCTS", "Aminabad Road, Lucknow 226018", g)],
        ["gstin", "legal_status"], [])

    # 8. conflicting business names --------------------------------------------------------------
    g = gstin("19", "FPKPD6089L")
    add("900100008", "Conflicting company names",
        "Invoice and sign board name different businesses. The app shows both and asks which is right.",
        [invoice("BENGAL STEEL MART", g, "Burrabazar, Kolkata 700007 West Bengal", [product("TMT Bar 12mm", "Kg", 64)]),
         sign_board("EASTERN STEEL TRADING", "Burrabazar, Kolkata 700007", g),
         cheque("BENGAL STEEL MART", "Burrabazar Branch, Kolkata 700007")],
        ["company_name"], [])

    # 9. Udyam vs GSTIN state conflict -----------------------------------------------------------
    g = gstin("36", "GJWPT1146N")
    add("900100009", "Udyam and GSTIN disagree on state",
        "The Udyam certificate puts the unit in Karnataka but the GSTIN is a Telangana one, so the state is "
        "flagged and a risk flag is raised.",
        [udyam("NIZAM PRECISION TOOLS", "BENGALURU", "KARNATAKA", "560058", g, state_code_ok=False),
         invoice("NIZAM PRECISION TOOLS", g, "Jeedimetla, Hyderabad 500055 Telangana", [product("Cutting Insert", "Nos", 410)])],
        ["city", "state", "pincode"], [])

    # 10. partnership firm with one gap ----------------------------------------------------------
    g = gstin("23", "HQVFB9201C")
    add("900100010", "Partnership firm, 1 to collect",
        "Two documents agree on name, GSTIN and city, but neither gives a pincode, so only that is collected.",
        [invoice("BHOPAL BROTHERS & CO", g, "MP Nagar Zone 1, Bhopal, Madhya Pradesh", [product("Office Chairs", "Nos", 2400)]),
         sign_board("BHOPAL BROTHERS & CO", "MP Nagar Zone 1, Bhopal", g)],
        [], ["pincode"])
    return S


# ----------------------------------------------------------------------------
# writers
# ----------------------------------------------------------------------------

def write_files():
    OUT.mkdir(exist_ok=True)
    S = sellers()
    rows, doc_json = [], []
    for s in S:
        docs = []
        for dtype, ext in s["docs"]:
            rows.append({"fk_glusr_usr_id": s["glid"], "document_type": dtype,
                         "llm_extraction": json.dumps(ext, ensure_ascii=False, separators=(",", ":"))})
            docs.append({"doc_type": dtype, "extraction": ext})
        doc_json.append({"seller_id": s["glid"], "documents": docs})

    with open(OUT / "sample_10_sellers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["fk_glusr_usr_id", "document_type", "llm_extraction"])
        w.writeheader()
        w.writerows(rows)

    # JSON layout: one object keyed by seller id, each a list of documents
    (OUT / "sample_10_sellers.json").write_text(
        json.dumps({d["seller_id"]: d["documents"] for d in doc_json}, indent=2, ensure_ascii=False), encoding="utf-8")

    with open(OUT / "sample_10_sellers_scenarios.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["glid", "scenario", "documents", "expected_to_confirm", "expected_to_collect", "what_to_look_for"])
        for s in S:
            w.writerow([s["glid"], s["title"], " + ".join(d for d, _ in s["docs"]),
                        ", ".join(s["confirm"]) or "-", ", ".join(s["collect"]) or "-", s["note"]])
    return S, len(rows)


def write_readme(S):
    lines = [README_TOP, "| GLID | Scenario | Documents | App will confirm | App will collect | What to look for |", "|---|---|---|---|---|---|"]
    for s in S:
        lines.append("| {} | **{}** | {} | {} | {} | {} |".format(
            s["glid"], s["title"], ", ".join(d for d, _ in s["docs"]),
            ", ".join(s["confirm"]) or "-", ", ".join(s["collect"]) or "-", s["note"]))
    (OUT / "README.md").write_text("\n".join(lines) + "\n" + README_BOTTOM, encoding="utf-8")


def write_zip():
    import zipfile
    with zipfile.ZipFile(OUT / "seller_enrichment_test_pack.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("sample_10_sellers.csv", "sample_10_sellers.json", "sample_10_sellers_scenarios.csv", "README.md"):
            z.write(OUT / name, name)


def check(S):
    from src import enrich as enr
    engine = enr.load_engine()
    report = enr.ParseReport()
    grouped = {}
    data = (OUT / "sample_10_sellers.csv").read_bytes()
    for sid, docs in enr.parse_upload("sample_10_sellers.csv", data, report).items():
        grouped.setdefault(sid, []).extend(docs)
    results = enr.enrich(grouped, engine, None)
    print(f"read {report.docs_read} documents, skipped {report.docs_skipped_type + report.docs_skipped_json}\n")
    ok = True
    for s in S:
        t = enr.triage_profile(results[s["glid"]], None)
        confirm = [f["key"] for f in t["fields"] if f["bucket"] in ("medium", "low") and f["value"]]
        collect = [f["key"] for f in t["fields"] if f["bucket"] == "missing"]
        good = sorted(confirm) == sorted(s["confirm"]) and sorted(collect) == sorted(s["collect"])
        ok &= good
        print(f"{'OK ' if good else 'XX '} {s['glid']}  {s['title']}")
        print(f"      confirm {confirm}  (want {s['confirm']})   collect {collect}  (want {s['collect']})")
        if not good:
            for f in t["fields"]:
                print(f"        {f['key']:<13} {f['bucket']:<8} {f['confidence'] if f['confidence'] is None else round(f['confidence'], 2)}  {f['value']}")
        if t["risk_flags"]:
            print(f"      risk flags: {t['risk_flags']}")
    print("\nALL SCENARIOS MATCH" if ok else "\nSOME SCENARIOS DIFFER")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    S, n = write_files()
    write_readme(S)
    write_zip()
    print(f"wrote {n} documents for {len(S)} sellers to {OUT}")
    if a.check:
        sys.exit(0 if check(S) else 1)
