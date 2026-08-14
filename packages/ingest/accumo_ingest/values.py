"""Parse the messy numbers and dates real ERP exports actually contain.

Money is Decimal. Never float.
Dates: ISO and Excel serials are unambiguous.
DD/MM vs MM/DD is not guessed — the caller must pass date_format.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

EXCEL_EPOCH = date(1899, 12, 30)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SLASH = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
_CURRENCIES = {"INR", "AED", "USD", "EUR", "GBP", "SAR", "QAR", "OMR", "KWD", "BHD"}


def parse_amount(raw: object | None) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
        return Decimal(str(raw)).quantize(Decimal("0.0001"))
    s = str(raw).strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    tail = s[-2:].upper()
    if tail in ("CR", "DR") and len(s) > 2 and not s[-3].isalpha():
        if tail == "CR":
            negative = True
        s = s[:-2]
    s = s.replace("₹", "").replace("AED", "").replace(",", "").replace(" ", "")
    if s in {"", "-", "--"}:
        return None
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not an amount: {raw!r}")
    if negative:
        value = -value
    return value.quantize(Decimal("0.0001"))


def parse_date(raw: object | None, date_format: str | None = None) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # Excel serial. 1 = 1899-12-31; Excel's leap-year bug is absorbed by the 1899-12-30 epoch.
        return EXCEL_EPOCH + timedelta(days=int(raw))
    s = str(raw).strip()
    if not s:
        return None
    m = _ISO.match(s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _SLASH.match(s)
    if not m:
        raise ValueError(f"not a date: {raw!r}")
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    if date_format == "ymd":
        raise ValueError(f"not a YMD date: {raw!r}")
    if date_format == "dmy":
        return date(y, b, a)
    if date_format == "mdy":
        return date(y, a, b)
    # Unambiguous if one side is > 12.
    if a > 12 and b <= 12:
        return date(y, b, a)
    if b > 12 and a <= 12:
        return date(y, a, b)
    raise ValueError("ambiguous date — pass date_format 'dmy' or 'mdy'")


def date_is_ambiguous(raw: object | None) -> bool:
    if raw is None or isinstance(raw, (date, datetime, int, float)):
        return False
    s = str(raw).strip()
    if _ISO.match(s):
        return False
    m = _SLASH.match(s)
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return a <= 12 and b <= 12


def parse_currency(raw: object | None, default: str = "INR") -> str:
    if raw is None or str(raw).strip() == "":
        return default
    code = str(raw).strip().upper()
    if code == "RS" or code == "₹":
        code = "INR"
    if code not in _CURRENCIES:
        raise ValueError(f"unrecognised currency: {raw!r}")
    return code
