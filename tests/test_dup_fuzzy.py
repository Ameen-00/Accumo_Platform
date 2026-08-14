from datetime import date
from decimal import Decimal
from uuid import uuid4

from accumo_pulse.rules.dup_fuzzy import DupFuzzy
from accumo_rules.context import AllocatedPayment
from accumo_rules.fingerprint import fingerprint


def _p(**kw) -> AllocatedPayment:
    return AllocatedPayment(
        payment_id=kw.get("payment_id") or uuid4(),
        invoice_id=kw.get("invoice_id") or uuid4(),
        invoice_norm=kw["invoice_norm"],
        invoice_number=kw.get("invoice_number", kw["invoice_norm"]),
        amount=Decimal(kw.get("amount", "88500")),
        currency="INR",
        payment_date=kw.get("payment_date", date(2025, 7, 10)),
        vendor_identity_id=kw["ident"],
        vendor_name="Cochin Packing",
    )


def test_near_invoice_numbers_same_amount_flag():
    ident = uuid4()
    rows = [
        _p(ident=ident, invoice_norm="INV20250412", invoice_number="INV/2025/0412", payment_date=date(2025, 7, 10)),
        _p(ident=ident, invoice_norm="INV2025412", invoice_number="INV-2025-412", payment_date=date(2025, 7, 14)),
    ]
    findings = list(DupFuzzy().run(rows))
    assert len(findings) == 1
    assert findings[0].amount_at_risk == Decimal("88500.0000")
    assert findings[0].explanation["similarity"] >= 85


def test_exact_same_invoice_norm_is_left_to_dup_exact():
    ident = uuid4()
    rows = [
        _p(ident=ident, invoice_norm="INV20251044", payment_date=date(2025, 6, 5)),
        _p(ident=ident, invoice_norm="INV20251044", payment_date=date(2025, 6, 7)),
    ]
    assert list(DupFuzzy().run(rows)) == []


def test_monthly_instalment_is_excluded():
    ident = uuid4()
    rows = [
        _p(ident=ident, invoice_norm="RENT001", payment_date=date(2025, 1, 1), amount="50000"),
        _p(ident=ident, invoice_norm="RENT002", payment_date=date(2025, 2, 1), amount="50000"),
    ]
    assert list(DupFuzzy().run(rows)) == []


def test_fingerprint_differs_from_exact_rule():
    parts = ["p1", "p2"]
    assert fingerprint("DUP_FUZZY", *parts) != fingerprint("DUP_EXACT", *parts)
