from accumo_ingest.classify import classify_name, profile
from accumo_ingest.gstr2b import TwoBRow
from accumo_ingest.invoice_pdf import parse_invoice_text
from accumo_rules.completeness import invoice_not_in_2b, two_b_not_in_invoices


SAMPLE = """
Securseed Infosec Services Ltd
GSTIN 29ABJCS2365M1ZO
# : INV-000076
Invoice Date : 30/05/2025
Bill To
Prime Guardian
GSTIN 32AAZFP6402E1Z7
Total ₹7,78,218.48
Balance Due ₹7,78,218.48
"""


def test_revised_estimate_same_job_not_monthly_retainer():
    from accumo_rules.suggest import revised_documents

    original = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    revised = parse_invoice_text(
        SAMPLE.replace("INV-000076", "INV-000076A").replace("30/05/2025", "05/06/2025"),
        "INV-000076A.pdf",
    )
    hits = list(revised_documents([original, revised]))
    assert len(hits) == 1
    assert "INV-000076" in hits[0].title and "INV-000076A" in hits[0].title

    other = parse_invoice_text(
        SAMPLE.replace("INV-000076", "INV-000082").replace("7,78,218.48", "3,89,109.24"),
        "INV-000082.pdf",
    )
    assert list(revised_documents([original, other])) == []


def test_briefing_tells_first_time_user_where_to_start():
    from accumo_foundation.guide import briefing, next_action

    card = briefing({"dup_docs": 3, "credits": 5, "suggested": 10, "open_invoices": 11, "invoices": 49, "payments": 109, "two_b": 144, "open_bank": 7})
    assert "Possible mistakes" in card["start"]
    assert "49 bills in this drop" in card["spoken"]
    assert "7 bank payments with no bill" in card["spoken"]
    assert "one bank file" in card["spoken"]
    assert "cash" in card["spoken"]
    assert any("credit notes" in s for s in card["steps"])
    assert "never books" in card["steps"][-1]
    assert "other month" in next_action("OPEN_INVOICE", {"other_period": True}).lower()
    assert "both files" in next_action("DUP_DOC").lower()


def test_classifies_zero_books_bundle():
    kinds = [
        classify_name("INV-000076.pdf"),
        classify_name("Acct_Statement_XXXXXXXX1071_18042026.xls"),
        classify_name("GSTR-2B Consolidation.xlsx"),
        classify_name("Pulse_AI_Training_01_Zero_Books.xlsx"),
    ]
    env = profile(kinds)
    assert kinds[0].kind == "invoice_pdf"
    assert kinds[1].kind == "bank_statement"
    assert kinds[2].kind == "gstr2b"
    assert kinds[3].skip
    assert env.mode == "zero_books"


def test_classifies_proper_books():
    env = profile([classify_name("Account Transactions (1).pdf")])
    assert env.mode == "proper_books"


def test_desk_raises_open_invoice_and_credit():
    from accumo_ingest.bank_statement import BankLine
    from accumo_rules.desk import build_desk

    inv = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    two_b = [
        TwoBRow(
            supplier_gstin="09AAFCM7916H1Z6",
            supplier_name="NIVA BUPA",
            invoice_number="CN-1",
            invoice_date="01/06/2025",
            invoice_value="38747.84",
            taxable="32837",
            igst="5910",
            cgst="0",
            sgst="0",
            itc_available="Yes",
            kind="credit_note",
        )
    ]
    desk = build_desk([inv], [BankLine("01/01/26", "SALARY", "x", "100", "out", "1")], two_b)
    assert desk["OPEN_INVOICE"]
    assert "other period" in desk["OPEN_INVOICE"][0].title
    assert desk["CREDIT_UNAPPLIED"]
    assert desk["COMP_2B_ORPHAN"] == []  # credit notes are not b2b orphans


def test_duplicate_document_and_amount_match():
    from accumo_ingest.bank_statement import BankLine
    from accumo_rules.suggest import duplicate_documents, suggest_matches

    a = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    b = parse_invoice_text(SAMPLE, "INV-000076 (1).pdf")
    dups = list(duplicate_documents([a, b]))
    assert len(dups) == 1
    bank = [
        BankLine(
            payment_date="05/06/25",
            narration="NEFT SECURSEED",
            reference="UTR1",
            amount="778218.48",
            direction="out",
            balance="1",
        )
    ]
    hits = list(suggest_matches([a], bank))
    assert len(hits) == 1
    assert "Confirm" in hits[0].title


def test_skips_workpapers():
    kind = classify_name("903_Prime Guardian_2025-26.pdf")
    assert kind.skip
    assert "fake payable" in kind.reason
    env = profile([kind, classify_name("INV-000076.pdf")])
    assert any("fake payable" in line for line in env.limitations)


def test_invoice_pdf_fields():
    inv = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    assert inv.invoice_number == "INV-000076"
    assert inv.vendor_tax_id == "29ABJCS2365M1ZO"
    assert inv.buyer_tax_id == "32AAZFP6402E1Z7"
    assert inv.amount == "778218.48"
    assert not inv.needs_human


ZOHO_SAMPLE = """
Prime Guardian Cyber Security Services
Account Transactions
Secured Infosec Services Limited
Basis: Accrual
From 01/04/2025 To 31/03/2026
Date Account Transaction Details Transaction Type Transaction# Reference# Debit Credit Amount
As On 01/04/2025 Opening Balance ₹57,61,780.82
03/04/2025 Secured Infosec NEFT DR- Journal PV/23-24/772 29,72,390.00 29,72,390.00 Dr
30/06/2025 Secured Infosec Vishnu Ramesh : 1 Journal PV/23-24/898 Inv no 78 3,89,109.24 3,89,109.24 Cr
30/11/2025 Secured Infosec Yash Rajput : [01 Journal PV/23-24/1026 INV-000109 2,48,539.31 2,48,539.31 Cr
Total Debits and Credits (01/04/2025 - 31/03/2026) ₹2,12,46,421.43 ₹1,84,32,742.58
"""


def test_zoho_ledger_credits_and_debits():
    from accumo_ingest.adapt import ledger_as_invoices, ledger_as_payment_rows, merge_invoices
    from accumo_ingest.zoho_ledger import parse_zoho_text

    lines = parse_zoho_text(ZOHO_SAMPLE)
    assert len(lines) == 3
    pay = next(l for l in lines if l.kind == "payment")
    bills = [l for l in lines if l.kind == "invoice"]
    assert pay.amount == "2972390.00"
    assert pay.voucher == "PV/23-24/772"
    assert {b.reference for b in bills} == {"INV-000078", "INV-000109"}
    bill = next(b for b in bills if b.reference == "INV-000078")
    assert bill.amount == "389109.24"
    invoices = ledger_as_invoices(lines)
    assert invoices[0].invoice_number == "INV-000078"
    payments = ledger_as_payment_rows(lines)
    assert payments[0]["payment_id"] == "PV/23-24/772"
    pdf = parse_invoice_text(SAMPLE.replace("INV-000076", "INV-000078"), "INV-000078.pdf")
    merged = merge_invoices([pdf], invoices)
    assert {i.invoice_number for i in merged} == {"INV-000078", "INV-000109"}
    assert next(i for i in merged if i.invoice_number == "INV-000078").vendor_tax_id == "29ABJCS2365M1ZO"
    leftover = merge_invoices([parse_invoice_text(SAMPLE, "INV-000076.pdf")], invoices)
    assert {i.invoice_number for i in leftover} == {"INV-000076", "INV-000078", "INV-000109"}


def test_open_invoice_says_other_period():
    from accumo_ingest.bank_statement import BankLine
    from accumo_rules.desk import open_invoices

    inv = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    bank = [BankLine("15/01/2026", "NEFT RENT", "UTR9", "50000", "out", "1")]
    findings = list(open_invoices([inv], bank))
    assert len(findings) == 1
    assert "other period" in findings[0].title
    assert "May 2025" in findings[0].title
    assert "January 2026" in findings[0].title
    assert findings[0].explanation["other_period"] is True


def test_open_invoice_silent_without_bank():
    from accumo_rules.desk import open_invoices

    inv = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    assert list(open_invoices([inv], [])) == []


def test_2b_completeness_both_directions():
    inv = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    two_b = [
        TwoBRow(
            supplier_gstin="29ABJCS2365M1ZO",
            supplier_name="SECURSEED",
            invoice_number="INV-000099",
            invoice_date="01/06/2025",
            invoice_value="1000",
            taxable="847.46",
            igst="152.54",
            cgst="0",
            sgst="0",
            itc_available="Yes",
            kind="b2b",
        )
    ]
    missing = list(invoice_not_in_2b([inv], two_b))
    orphan = list(two_b_not_in_invoices([inv], two_b, claim_complete=True))
    assert len(missing) == 1
    assert "INV-000076" in missing[0].title
    assert orphan
    assert any("other period" in f.title or "INV-000099" in f.title for f in orphan)


def test_2b_orphan_same_month_is_listed():
    inv = parse_invoice_text(SAMPLE, "INV-000076.pdf")
    two_b = [
        TwoBRow(
            supplier_gstin="29ABJCS2365M1ZO",
            supplier_name="SECURSEED",
            invoice_number="INV-000099",
            invoice_date="31/05/2025",
            invoice_value="1000",
            taxable="847.46",
            igst="152.54",
            cgst="0",
            sgst="0",
            itc_available="Yes",
            kind="b2b",
        )
    ]
    orphan = list(two_b_not_in_invoices([inv], two_b, claim_complete=True))
    assert len(orphan) == 1
    assert "INV-000099" in orphan[0].title


def test_2b_credit_note_two_row_header():
    from io import BytesIO

    from openpyxl import Workbook

    from accumo_ingest.gstr2b import parse_2b_bytes

    wb = Workbook()
    ws = wb.active
    ws.title = "Credit Note"
    ws.append(["Goods and Services Tax  - GSTR-2B"])
    ws.append([])
    ws.append([])
    ws.append(["Debit/Credit notes (Original)"])
    ws.append(["GSTIN of supplier", "Trade/Legal name", "Credit note/Debit note details", "", "", "", ""])
    ws.append(["", "", "Note number", "Note type", "Note Supply type", "Note date", "Note Value (₹)"])
    ws.append(["09AAFCM7916H1Z6", "NIVA BUPA", "51011500202400JU", "Credit Note", "Regular", "06/06/2025", "38747.84"])
    ws.append(["09AAFCM7916H1Z6", "NIVA BUPA", "DN-1", "Debit Note", "Regular", "07/06/2025", "100"])
    buf = BytesIO()
    wb.save(buf)
    rows = parse_2b_bytes(buf.getvalue())
    assert len(rows) == 1
    assert rows[0].kind == "credit_note"
    assert rows[0].invoice_number == "51011500202400JU"
    assert rows[0].invoice_value == "38747.84"


def test_ledger_without_gstin_is_not_itc_risk():
    from accumo_ingest.adapt import ledger_as_invoices
    from accumo_ingest.zoho_ledger import parse_zoho_text

    lines = parse_zoho_text(ZOHO_SAMPLE)
    invoices = ledger_as_invoices(lines)
    assert invoices
    assert all(not i.vendor_tax_id for i in invoices)
    assert list(invoice_not_in_2b(invoices, [])) == []
