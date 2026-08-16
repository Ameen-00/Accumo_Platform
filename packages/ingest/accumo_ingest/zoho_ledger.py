"""Zoho Books 'Account Transactions' PDF → invoice / payment rows.

Credits on a supplier ledger are bills. Debits are payments.
Zoho wraps cells, so we parse the extracted text — not the empty tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO

ROW_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<body>.+?)\s+"
    r"(?P<vtype>Journal|Payment|Invoice|Bill|Credit\s*Note)\s+"
    r"(?P<voucher>PV/\d{2}-\d{2}/\d+)\s+"
    r"(?:(?:Inv\s*no\.?\s*(?P<inv>\d+)|(?P<invfull>INV[- ]?\d+))\s+)?"
    r"(?P<a1>[\d,]+\.\d{2})(?:\s+(?P<a2>[\d,]+\.\d{2}))?\s+"
    r"(?P<dc>Dr|Cr)\s*$",
    re.I,
)
FROM_RE = re.compile(r"From\s+(\d{2}/\d{2}/\d{4})\s+To\s+(\d{2}/\d{2}/\d{4})", re.I)


@dataclass
class LedgerLine:
    kind: str  # invoice | payment
    date: str
    vendor: str
    details: str
    reference: str
    amount: str
    voucher: str


def _money(raw: str) -> str:
    try:
        return str(Decimal(raw.replace(",", "")))
    except (InvalidOperation, ValueError):
        return ""


def _invoice_number(digits: str | None, full: str | None) -> str:
    if digits:
        return f"INV-{digits.zfill(6)}"
    if full:
        cleaned = full.upper().replace(" ", "")
        if cleaned.startswith("INV") and not cleaned.startswith("INV-"):
            cleaned = "INV-" + cleaned[3:]
        m = re.search(r"(\d+)$", cleaned)
        if m:
            return f"INV-{m.group(1).zfill(6)}"
        return cleaned
    return ""


def _account_name(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.lower() == "account transactions" and i + 1 < len(lines):
            nxt = lines[i + 1]
            if not nxt.lower().startswith("basis"):
                return nxt[:120]
    return ""


def extract_text(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""
    with pdfplumber.open(BytesIO(data)) as doc:
        return "\n".join((page.extract_text() or "") for page in doc.pages)


def parse_zoho_text(text: str) -> list[LedgerLine]:
    vendor = _account_name(text)
    lines: list[LedgerLine] = []
    for raw in text.splitlines():
        row = ROW_RE.match(raw.strip())
        if not row:
            continue
        amt = _money(row.group("a2") or row.group("a1"))
        if not amt:
            continue
        credit = row.group("dc").lower() == "cr"
        details = re.sub(r"\s+", " ", row.group("body")).strip()
        if vendor and details.lower().startswith(vendor.lower()[:20].lower()):
            # Keep the rest as the narration when the account name is repeated.
            rest = details[len(vendor) :].strip(" -")
            if rest:
                details = rest
        lines.append(
            LedgerLine(
                kind="invoice" if credit else "payment",
                date=row.group("date"),
                vendor=vendor or details[:80],
                details=details,
                reference=_invoice_number(row.group("inv"), row.group("invfull")),
                amount=amt,
                voucher=row.group("voucher"),
            )
        )
    return lines


def parse_zoho_ledger(data: bytes) -> list[LedgerLine]:
    text = extract_text(data)
    if not text.strip():
        return []
    return parse_zoho_text(text)


def ledger_period(text: str) -> tuple[str, str] | None:
    hit = FROM_RE.search(text)
    if not hit:
        return None
    return hit.group(1), hit.group(2)
