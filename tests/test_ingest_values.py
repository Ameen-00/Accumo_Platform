from datetime import date
from decimal import Decimal

import pytest

from accumo_ingest.values import date_is_ambiguous, parse_amount, parse_currency, parse_date


def test_indian_grouping_and_parens_and_cr():
    assert parse_amount("1,23,456.78") == Decimal("123456.7800")
    assert parse_amount("(1,200.50)") == Decimal("-1200.5000")
    assert parse_amount("500.00 CR") == Decimal("-500.0000")
    assert parse_amount("500.00 DR") == Decimal("500.0000")


def test_iso_and_excel_serial_dates():
    assert parse_date("2026-03-07") == date(2026, 3, 7)
    assert parse_date(1) == date(1899, 12, 31)


def test_does_not_guess_slash_dates():
    assert date_is_ambiguous("03/07/2026") is True
    with pytest.raises(ValueError, match="ambiguous"):
        parse_date("03/07/2026")
    assert parse_date("03/07/2026", "dmy") == date(2026, 7, 3)
    assert parse_date("03/07/2026", "mdy") == date(2026, 3, 7)
    assert parse_date("15/07/2026") == date(2026, 7, 15)


def test_currency_aliases():
    assert parse_currency("Rs") == "INR"
    assert parse_currency(None, "AED") == "AED"
    with pytest.raises(ValueError):
        parse_currency("BTC")
