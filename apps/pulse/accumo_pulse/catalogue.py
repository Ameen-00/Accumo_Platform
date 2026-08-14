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
]
