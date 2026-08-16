"""Completeness findings. Not recovery — they say the record is incomplete.

A human must still decide. These never auto-confirm and never count as saved.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal, InvalidOperation

from accumo_canonical.normalise import normalise_invoice
from accumo_ingest.gstr2b import TwoBRow
from accumo_ingest.invoice_pdf import InvoiceExtract
from accumo_ingest.values import parse_date
from accumo_rules.engine import Finding

COMP_2B_MISSING = "COMP_2B_MISSING"
COMP_2B_ORPHAN = "COMP_2B_ORPHAN"
ORPHAN_SHOW = 8


def _norm(n: str) -> str:
    return normalise_invoice(n or "")


def _as_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return parse_date(raw, "dmy")
    except ValueError:
        return None


def _month_span(dates: list[date]) -> str:
    if not dates:
        return ""
    first, last = min(dates), max(dates)
    if (first.year, first.month) == (last.year, last.month):
        return first.strftime("%B %Y")
    return f"{first.strftime('%B %Y')}–{last.strftime('%B %Y')}"


def _amt(raw: str) -> Decimal:
    try:
        return Decimal(str(raw or "0").replace(",", ""))
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def invoice_not_in_2b(invoices: list[InvoiceExtract], two_b: list[TwoBRow]) -> Iterator[Finding]:
    present = {_norm(r.invoice_number) for r in two_b if r.kind == "b2b"}
    two_b_dates = [d for d in (_as_date(r.invoice_date) for r in two_b if r.kind == "b2b") if d]
    two_b_label = _month_span(two_b_dates)
    for inv in invoices:
        key = _norm(inv.invoice_number)
        if not key or key in present:
            continue
        # Ledger reconstructions without a GSTIN are not an ITC claim.
        if not (inv.vendor_tax_id or "").strip():
            continue
        amt = _amt(inv.amount)
        inv_date = _as_date(inv.invoice_date)
        other_period = False
        if inv_date and two_b_dates:
            lo, hi = min(two_b_dates), max(two_b_dates)
            other_period = not ((lo.year, lo.month) <= (inv_date.year, inv_date.month) <= (hi.year, hi.month))
        if other_period:
            title = (
                f"{inv.invoice_number} is from {inv_date.strftime('%B %Y')}; "
                f"this GSTR-2B covers {two_b_label} — other period, ITC not necessarily at risk"
            )
            why = (
                "The bill and the GST portal file are from different months. "
                "This is a period gap, not proof the credit is lost."
            )
        else:
            title = f"Invoice {inv.invoice_number} is not on GSTR-2B — ITC may be at risk"
            why = "The invoice was captured from a document but no matching 2B row was found."
        yield Finding(
            amount_at_risk=amt,
            currency=inv.currency or "INR",
            confidence=Decimal("0.50") if other_period else Decimal("0.80"),
            title=title,
            explanation={
                "why": why,
                "invoice": inv.invoice_number,
                "vendor": inv.vendor_name,
                "gstin": inv.vendor_tax_id,
                "invoice_date": inv.invoice_date,
                "gstr2b_period": two_b_label,
                "other_period": other_period,
                "rule": COMP_2B_MISSING,
            },
            evidence={"invoice_number": inv.invoice_number, "vendor_tax_id": inv.vendor_tax_id},
            fingerprint_parts=[COMP_2B_MISSING, key, inv.vendor_tax_id],
        )


def two_b_not_in_invoices(
    invoices: list[InvoiceExtract],
    two_b: list[TwoBRow],
    *,
    claim_complete: bool = False,
) -> Iterator[Finding]:
    b2b = [r for r in two_b if r.kind == "b2b"]
    # Partial invoice drops must not drown the reviewer in 2B orphans.
    if not claim_complete and len(invoices) < max(8, int(0.5 * len(b2b))):
        return
    have = {_norm(i.invoice_number) for i in invoices if i.invoice_number}
    inv_dates = [d for d in (_as_date(i.invoice_date) for i in invoices) if d]
    inv_label = _month_span(inv_dates)
    same: list[TwoBRow] = []
    other: list[TwoBRow] = []
    for row in b2b:
        key = _norm(row.invoice_number)
        if not key or key in have:
            continue
        row_date = _as_date(row.invoice_date)
        if row_date and inv_dates:
            lo, hi = min(inv_dates), max(inv_dates)
            in_span = (lo.year, lo.month) <= (row_date.year, row_date.month) <= (hi.year, hi.month)
            if not in_span:
                other.append(row)
                continue
        same.append(row)

    if other:
        total = sum((_amt(r.invoice_value) for r in other), start=Decimal("0"))
        yield Finding(
            amount_at_risk=total,
            currency="INR",
            confidence=Decimal("0.45"),
            title=(
                f"GSTR-2B also has {len(other)} invoices from months outside the bills you dropped"
                + (f" ({inv_label})" if inv_label else "")
                + " — other period, not missing from this drop"
            ),
            explanation={
                "why": (
                    "The GST portal file covers more months than the bills in this drop. "
                    "This is a period gap, not proof those bills were never received."
                ),
                "count": len(other),
                "bill_period": inv_label,
                "examples": [f"{r.invoice_number} ({r.supplier_name})" for r in other[:8]],
                "other_period": True,
                "rule": COMP_2B_ORPHAN,
            },
            evidence={"count": len(other)},
            fingerprint_parts=[COMP_2B_ORPHAN, "other-period", str(len(other))],
        )

    same.sort(key=lambda r: _amt(r.invoice_value), reverse=True)
    if len(same) > ORPHAN_SHOW:
        leftover = same[ORPHAN_SHOW:]
        total = sum((_amt(r.invoice_value) for r in leftover), start=Decimal("0"))
        yield Finding(
            amount_at_risk=total,
            currency="INR",
            confidence=Decimal("0.60"),
            title=(
                f"GSTR-2B has {len(same)} supplier invoices you did not drop as bills. "
                f"Showing the largest {ORPHAN_SHOW}; {len(leftover)} more total {total}."
            ),
            explanation={
                "why": "The portal lists more bills than this drop. Confirm they are other files, other period, or missing.",
                "count": len(same),
                "shown": ORPHAN_SHOW,
                "rule": COMP_2B_ORPHAN,
            },
            evidence={"count": len(same)},
            fingerprint_parts=[COMP_2B_ORPHAN, "summary", str(len(same))],
        )
        same = same[:ORPHAN_SHOW]

    for row in same:
        amt = _amt(row.invoice_value)
        yield Finding(
            amount_at_risk=amt,
            currency="INR",
            confidence=Decimal("0.75"),
            title=f"GSTR-2B has {row.invoice_number} ({row.supplier_name}) with no captured invoice",
            explanation={
                "why": "The portal shows a supplier invoice we have not captured. Completeness gap.",
                "invoice": row.invoice_number,
                "vendor": row.supplier_name,
                "gstin": row.supplier_gstin,
                "invoice_date": row.invoice_date,
                "rule": COMP_2B_ORPHAN,
            },
            evidence={"invoice_number": row.invoice_number, "vendor_tax_id": row.supplier_gstin},
            fingerprint_parts=[COMP_2B_ORPHAN, _norm(row.invoice_number), row.supplier_gstin],
        )
