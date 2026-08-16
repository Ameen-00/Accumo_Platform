"""Pulse rule catalogue. Seed writes these; the pack reads the codes."""

RULES = [
    ("DUP_EXACT", "Exact duplicate payment", "Same vendor, same invoice, same amount, paid more than once.", "recovery", {"window_days": 365}),
    ("DUP_FUZZY", "Probable duplicate", "Same vendor and amount, invoice numbers almost match.", "recovery", {"window_days": 90, "min_similarity": 85}),
    ("DUP_VENDOR", "Duplicate vendor master", "One real supplier living under two vendor codes.", "risk", {}),
    ("BANK_CHANGE_PAY", "Bank detail changed, then paid", "Vendor account changed and a payment followed.", "risk", {"window_days": 30}),
    ("NO_PO", "Payment without PO or receipt", "Paid where process required a PO or GRN.", "risk", {"min_amount": None, "require_grn": True}),
    ("THRESHOLD", "Approval limit circumvention", "Several payments just under a limit, same vendor, short window.", "risk", {"thresholds": [], "window_days": 30, "min_count": 3}),
    ("VENDOR_IS_EMPLOYEE", "Vendor bank matches payroll", "A vendor is paid into an employee account.", "risk", {}),
    ("CREDIT_UNAPPLIED", "Credit note never applied", "Credit issued, still open, vendor still being paid.", "recovery", {"min_age_days": 60}),
    ("COMP_2B_MISSING", "Invoice not on GSTR-2B", "A captured invoice has no matching 2B row — ITC may be at risk.", "risk", {}),
    ("COMP_2B_ORPHAN", "2B invoice not captured", "GSTR-2B lists a supplier invoice we have not captured.", "risk", {}),
    ("MATCH_SUGGEST", "Possible payment for this invoice", "A bank outflow matches the invoice amount. A person must confirm.", "risk", {}),
    ("DUP_DOC", "Same invoice arrived twice", "Two files produced the same invoice number.", "risk", {}),
    (
        "DUP_REVISED",
        "Revised bill, same job",
        "Same supplier, same rupees, a new document — a revised estimate paid on top of the original.",
        "recovery",
        {"window_days": 90},
    ),
    ("OPEN_INVOICE", "Invoice not in this bank statement", "Captured bill with no equal bank outflow in the file you dropped.", "risk", {}),
    ("OPEN_BANK", "Bank lines without a captured invoice", "Outflows in the statement that this drop cannot explain.", "risk", {}),
    ("AMT_2B", "PDF amount differs from GSTR-2B", "Same invoice number, different rupees.", "risk", {}),
]
