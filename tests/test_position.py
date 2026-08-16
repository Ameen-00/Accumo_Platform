"""Supplier position -- the screen that replaces the exception queue."""

from decimal import Decimal
from uuid import uuid4

from accumo_rules.position import (
    CLEAR,
    DIFFERENCE,
    WAITING,
    SupplierInput,
    position_for,
    summarise,
)


def _s(**kw) -> SupplierInput:
    return SupplierInput(
        identity_id=kw.pop("identity_id", uuid4()),
        name=kw.pop("name", "ABC Traders"),
        **{k: (Decimal(str(v)) if k in {"invoiced", "paid", "credit_notes", "gst_difference"} else v)
           for k, v in kw.items()},
    )


def test_everything_ties_is_clear():
    p = position_for(_s(invoiced=100000, paid=100000, invoice_count=4,
                        payment_count=4, explained_payments=4))
    assert p.state == CLEAR
    assert p.headline == "clear"


def test_small_difference_is_not_worth_an_owners_attention():
    """Rs 12 is rounding or a part-payment in flight. Showing it costs more
    trust than it earns."""
    p = position_for(_s(invoiced=100012, paid=100000, invoice_count=4,
                        payment_count=4, explained_payments=4))
    assert p.state == CLEAR


def test_real_difference_shows_in_rupees_not_rule_codes():
    p = position_for(_s(invoiced=152000, paid=100000, invoice_count=5,
                        payment_count=4, explained_payments=4))
    assert p.state == DIFFERENCE
    assert p.headline == "INR 52,000 difference"


def test_credit_notes_reduce_what_was_owed():
    """Invoiced 100k, credit note 8k, paid 92k -- that is settled, not a
    Rs 8,000 shortfall."""
    p = position_for(_s(invoiced=100000, credit_notes=8000, paid=92000,
                        invoice_count=3, payment_count=3, explained_payments=3))
    assert p.state == CLEAR


def test_a_payment_pulse_cannot_explain_is_a_difference():
    p = position_for(_s(invoiced=100000, paid=100000, invoice_count=4,
                        payment_count=5, explained_payments=4))
    assert p.unexplained_payments == 1
    assert p.state == DIFFERENCE


def test_waiting_outranks_difference():
    """If we have already asked someone, the honest line is 'waiting on Rajesh',
    not 'you are short Rs 52,000'. We know the reason -- claiming a difference
    we can already explain is the confident wrongness that loses an owner in one
    screen."""
    p = position_for(_s(invoiced=152000, paid=100000, invoice_count=5,
                        payment_count=4, explained_payments=4,
                        open_questions=1, waiting_on="Rajesh"))
    assert p.state == WAITING
    assert p.headline == "waiting on Rajesh"


def test_gst_difference_shows_separately():
    p = position_for(_s(invoiced=100000, paid=100000, invoice_count=4,
                        payment_count=4, explained_payments=4,
                        gst_difference=28000))
    assert p.state == DIFFERENCE
    assert "GST" in p.headline


def test_summary_counts_and_sentence():
    out = summarise([
        _s(name="ABC Traders", invoiced=152000, paid=100000,
           invoice_count=5, payment_count=4, explained_payments=4),
        _s(name="XYZ Agencies", invoiced=100000, paid=100000,
           invoice_count=4, payment_count=4, explained_payments=4,
           gst_difference=28000),
        _s(name="Southern Steels", invoiced=50000, paid=50000,
           invoice_count=2, payment_count=2, explained_payments=2),
        _s(name="Kerala Cables", invoiced=90000, paid=40000,
           invoice_count=3, payment_count=1, explained_payments=1,
           open_questions=1, waiting_on="Rajesh"),
    ])
    assert out.checked == 4
    assert out.clear == 1
    assert out.differences == 2
    assert out.waiting == 1
    assert out.headline == (
        "4 suppliers checked -> 1 clear -> 2 differences -> 1 waiting on information"
    )


def test_biggest_money_is_at_the_top():
    """An owner should never scroll to find the problem."""
    out = summarise([
        _s(name="Small", invoiced=101000, paid=100000,
           invoice_count=1, payment_count=1, explained_payments=1),
        _s(name="Clear one", invoiced=50000, paid=50000,
           invoice_count=1, payment_count=1, explained_payments=1),
        _s(name="Big", invoiced=900000, paid=100000,
           invoice_count=1, payment_count=1, explained_payments=1),
        _s(name="Asked", invoiced=200000, paid=100000,
           invoice_count=1, payment_count=1, explained_payments=1,
           open_questions=1),
    ])
    assert [p.name for p in out.positions] == ["Big", "Small", "Asked", "Clear one"]
