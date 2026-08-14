from datetime import date
from decimal import Decimal
from uuid import uuid4

from accumo_pulse.rules.bank_change import BankChangePay, is_assessable
from accumo_rules.context import BankObservation, PaymentToBank


def _pay(**kw) -> PaymentToBank:
    return PaymentToBank(
        payment_id=kw.get("payment_id") or uuid4(),
        vendor_id=kw["vendor_id"],
        vendor_identity_id=kw["ident"],
        vendor_name="Southern Steels",
        account_norm=kw["account"],
        payment_date=kw["day"],
        amount=Decimal(kw.get("amount", "480000")),
        currency="INR",
    )


def test_payment_after_new_account_is_flagged():
    vendor, ident = uuid4(), uuid4()
    pays = [
        _pay(vendor_id=vendor, ident=ident, account="old", day=date(2025, 8, 1), amount="72000"),
        _pay(vendor_id=vendor, ident=ident, account="new", day=date(2025, 8, 12), amount="480000"),
    ]
    findings = list(BankChangePay().run(pays, []))
    assert len(findings) == 1
    assert findings[0].amount_at_risk == Decimal("480000.0000")
    assert findings[0].explanation["days_after_change"] == 0


def test_single_account_is_not_assessable_and_finds_nothing():
    vendor, ident = uuid4(), uuid4()
    pays = [
        _pay(vendor_id=vendor, ident=ident, account="only", day=date(2025, 8, 1)),
        _pay(vendor_id=vendor, ident=ident, account="only", day=date(2025, 8, 20)),
    ]
    assert is_assessable([], pays) is False
    assert list(BankChangePay().run(pays, [])) == []


def test_explicit_prior_observation_within_window():
    vendor, ident = uuid4(), uuid4()
    obs = [
        BankObservation(vendor, ident, "Southern Steels", "old", date(2025, 7, 1)),
        BankObservation(vendor, ident, "Southern Steels", "new", date(2025, 8, 1)),
    ]
    pays = [_pay(vendor_id=vendor, ident=ident, account="new", day=date(2025, 8, 10))]
    assert is_assessable(obs, pays) is True
    findings = list(BankChangePay().run(pays, obs))
    assert len(findings) == 1
    assert findings[0].explanation["days_after_change"] == 9


def test_outside_window_is_ignored():
    vendor, ident = uuid4(), uuid4()
    obs = [
        BankObservation(vendor, ident, "Southern Steels", "old", date(2025, 1, 1)),
        BankObservation(vendor, ident, "Southern Steels", "new", date(2025, 1, 2)),
    ]
    pays = [_pay(vendor_id=vendor, ident=ident, account="new", day=date(2025, 4, 1))]
    assert list(BankChangePay().run(pays, obs)) == []
