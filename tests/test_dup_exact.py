from datetime import date
from decimal import Decimal
from uuid import uuid4

from accumo_pulse.rules.dup_exact import DupExact, finding_fingerprint
from accumo_rules.context import AllocatedPayment


def _p(**kw) -> AllocatedPayment:
    ident = kw.get("ident") or uuid4()
    inv = kw.get("invoice_id") or uuid4()
    return AllocatedPayment(
        payment_id=kw.get("payment_id") or uuid4(),
        invoice_id=inv,
        invoice_norm=kw.get("invoice_norm", "INV20251044"),
        invoice_number=kw.get("invoice_number", "INV/2025/1044"),
        amount=Decimal(kw.get("amount", "240000")),
        currency=kw.get("currency", "INR"),
        payment_date=kw.get("payment_date", date(2025, 6, 5)),
        vendor_identity_id=ident,
        vendor_name=kw.get("vendor_name", "Southern Steels"),
    )


def test_two_same_invoice_payments_flag_the_extra():
    ident, inv = uuid4(), uuid4()
    rows = [
        _p(ident=ident, invoice_id=inv, payment_date=date(2025, 6, 5)),
        _p(ident=ident, invoice_id=inv, payment_date=date(2025, 6, 7)),
    ]
    findings = list(DupExact().run(rows))
    assert len(findings) == 1
    assert findings[0].amount_at_risk == Decimal("240000.0000")
    assert findings[0].confidence == Decimal("0.95")
    assert len(findings[0].evidence["payment_ids"]) == 2


def test_single_payment_is_not_a_finding():
    assert list(DupExact().run([_p()])) == []


def test_different_identities_are_not_duplicates():
    inv = uuid4()
    rows = [
        _p(ident=uuid4(), invoice_id=inv),
        _p(ident=uuid4(), invoice_id=inv, payment_date=date(2025, 6, 8)),
    ]
    assert list(DupExact().run(rows)) == []


def test_outside_window_is_ignored():
    ident, inv = uuid4(), uuid4()
    rows = [
        _p(ident=ident, invoice_id=inv, payment_date=date(2024, 1, 1)),
        _p(ident=ident, invoice_id=inv, payment_date=date(2025, 8, 1)),
    ]
    assert list(DupExact().run(rows, {"window_days": 365})) == []


def test_fingerprint_is_stable_across_runs():
    ident, inv, p1, p2 = uuid4(), uuid4(), uuid4(), uuid4()
    rows = [
        _p(ident=ident, invoice_id=inv, payment_id=p1, payment_date=date(2025, 6, 5)),
        _p(ident=ident, invoice_id=inv, payment_id=p2, payment_date=date(2025, 6, 7)),
    ]
    a = list(DupExact().run(rows))[0]
    b = list(DupExact().run(list(reversed(rows))))[0]
    assert finding_fingerprint(a) == finding_fingerprint(b)
