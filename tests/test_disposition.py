from decimal import Decimal

import pytest

from accumo_foundation.disposition import TransitionError, assert_transition


def test_happy_path_to_recovered():
    assert_transition("new", "in_review")
    assert_transition("in_review", "confirmed")
    assert_transition("confirmed", "recovered", recovered_amount=Decimal("100"))


def test_may_dismiss_from_new_or_review_with_reason():
    assert_transition("new", "dismissed", reason="false positive — instalment")
    assert_transition("in_review", "dismissed", reason="same payment, two rows")


def test_dismiss_without_reason_is_rejected():
    with pytest.raises(TransitionError, match="reason"):
        assert_transition("new", "dismissed", reason="  ")


def test_illegal_jumps_are_rejected():
    with pytest.raises(TransitionError):
        assert_transition("new", "recovered", recovered_amount=Decimal("1"))
    with pytest.raises(TransitionError):
        assert_transition("dismissed", "new")
    with pytest.raises(TransitionError):
        assert_transition("confirmed", "dismissed", reason="changed mind")


def test_recovery_needs_an_amount():
    with pytest.raises(TransitionError, match="amount"):
        assert_transition("confirmed", "recovered")
