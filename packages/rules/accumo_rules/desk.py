"""Everything we can raise from a messy drop. A human still decides."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation

from datetime import date

from accumo_canonical.normalise import normalise_invoice, normalise_name
from accumo_ingest.bank_statement import BankLine
from accumo_ingest.gstr2b import TwoBRow
from accumo_ingest.invoice_pdf import InvoiceExtract
from accumo_ingest.values import parse_date
from accumo_rules.completeness import COMP_2B_MISSING, COMP_2B_ORPHAN, invoice_not_in_2b, two_b_not_in_invoices
from accumo_rules.engine import Finding
from accumo_rules.suggest import (
    DUP_DOC,
    DUP_REVISED,
    MATCH_SUGGEST,
    duplicate_documents,
    revised_documents,
    suggest_matches,
)

CREDIT_UNAPPLIED = "CREDIT_UNAPPLIED"
DUP_VENDOR = "DUP_VENDOR"
OPEN_INVOICE = "OPEN_INVOICE"
OPEN_BANK = "OPEN_BANK"
AMT_2B = "AMT_2B"

INTEGRITY = frozenset(
    {
        "DUP_EXACT",
        "DUP_FUZZY",
        "DUP_VENDOR",
        "DUP_DOC",
        "DUP_REVISED",
        "BANK_CHANGE_PAY",
        "NO_PO",
        "THRESHOLD",
        "VENDOR_IS_EMPLOYEE",
        "CREDIT_UNAPPLIED",
    }
)
MATCH = frozenset({MATCH_SUGGEST})
COMPLETE = frozenset({COMP_2B_MISSING, COMP_2B_ORPHAN, OPEN_INVOICE, OPEN_BANK, AMT_2B})


def _dec(raw: object) -> Decimal | None:
    try:
        return Decimal(str(raw).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError):
        return None


def _tokens(name: str) -> set[str]:
    return {t for t in normalise_name(name).split() if len(t) >= 4}


def vendor_dups(invoices: list[InvoiceExtract]) -> Iterator[Finding]:
    by_gstin: dict[str, set[str]] = defaultdict(set)
    amounts: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for inv in invoices:
        gstin = (inv.vendor_tax_id or "").upper()
        if not gstin:
            continue
        by_gstin[gstin].add(inv.vendor_name)
        amounts[gstin] += _dec(inv.amount) or Decimal("0")
    for gstin, names in by_gstin.items():
        if len(names) < 2:
            continue
        yield Finding(
            amount_at_risk=amounts[gstin],
            currency="INR",
            confidence=Decimal("0.85"),
            title=f"Same GSTIN {gstin} under {len(names)} names. Confirm it is one supplier.",
            explanation={
                "why": "Two spellings, one tax id — the usual root of a duplicate payment later.",
                "gstin": gstin,
                "names": sorted(names),
                "rule": DUP_VENDOR,
            },
            evidence={"vendor_tax_id": gstin},
            fingerprint_parts=[DUP_VENDOR, gstin],
        )


def credit_notes(two_b: list[TwoBRow]) -> Iterator[Finding]:
    for row in two_b:
        if row.kind != "credit_note":
            continue
        amt = _dec(row.invoice_value) or Decimal("0")
        yield Finding(
            amount_at_risk=amt,
            currency="INR",
            confidence=Decimal("0.80"),
            title=f"Credit note {row.invoice_number} from {row.supplier_name} — confirm it was applied",
            explanation={
                "why": "GSTR-2B shows a credit. Pulse cannot see your books apply it. Confirm or dismiss.",
                "invoice": row.invoice_number,
                "vendor": row.supplier_name,
                "gstin": row.supplier_gstin,
                "rule": CREDIT_UNAPPLIED,
            },
            evidence={"invoice_number": row.invoice_number, "vendor_tax_id": row.supplier_gstin},
            fingerprint_parts=[CREDIT_UNAPPLIED, normalise_invoice(row.invoice_number), row.supplier_gstin],
        )


def amount_vs_2b(invoices: list[InvoiceExtract], two_b: list[TwoBRow]) -> Iterator[Finding]:
    portal = {
        normalise_invoice(r.invoice_number): r
        for r in two_b
        if r.kind == "b2b" and r.invoice_number
    }
    for inv in invoices:
        # Ledger reconstructions without a GSTIN are too weak to call an amount dispute.
        if not (inv.vendor_tax_id or "").strip():
            continue
        key = normalise_invoice(inv.invoice_number)
        row = portal.get(key)
        if not row:
            continue
        a, b = _dec(inv.amount), _dec(row.invoice_value)
        if a is None or b is None or a == b:
            continue
        diff = abs(a - b)
        if diff < Decimal("1"):
            continue
        yield Finding(
            amount_at_risk=diff,
            currency="INR",
            confidence=Decimal("0.85"),
            title=f"{inv.invoice_number}: PDF {a} vs GSTR-2B {b}",
            explanation={
                "why": "Same invoice number, different rupees. Confirm which figure is the payable.",
                "invoice": inv.invoice_number,
                "pdf_amount": str(a),
                "gstr2b_amount": str(b),
                "rule": AMT_2B,
            },
            evidence={"invoice_number": inv.invoice_number},
            fingerprint_parts=[AMT_2B, key],
        )


def name_matches(invoices: list[InvoiceExtract], bank: list[BankLine]) -> Iterator[Finding]:
    """Narration contains a vendor token — weaker than amount match, still useful."""
    outs = [b for b in bank if b.direction == "out"]
    bank_dates = [d for d in (_as_date(b.payment_date) for b in outs) if d]
    for inv in invoices:
        inv_date = _as_date(inv.invoice_date)
        if inv_date and bank_dates:
            lo, hi = min(bank_dates), max(bank_dates)
            if not ((lo.year, lo.month) <= (inv_date.year, inv_date.month) <= (hi.year, hi.month)):
                continue
        tokens = _tokens(inv.vendor_name)
        if not tokens:
            continue
        hits = []
        for line in outs:
            narr = normalise_name(line.narration)
            if any(t in narr for t in tokens):
                hits.append(line)
        if not hits:
            continue
        amt = _dec(inv.amount) or Decimal("0")
        yield Finding(
            amount_at_risk=amt,
            currency=inv.currency or "INR",
            confidence=Decimal("0.45"),
            title=f"{len(hits)} bank line(s) mention {inv.vendor_name[:40]} — check against {inv.invoice_number}",
            explanation={
                "why": "Name overlap only. Confirm the payment before treating the invoice as settled.",
                "invoice": inv.invoice_number,
                "vendor": inv.vendor_name,
                "narrations": [h.narration[:80] for h in hits[:6]],
                "rule": MATCH_SUGGEST,
            },
            evidence={"invoice_number": inv.invoice_number},
            fingerprint_parts=[MATCH_SUGGEST, "name", normalise_invoice(inv.invoice_number)],
        )


def _as_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return parse_date(raw, "dmy")
    except ValueError:
        try:
            return parse_date(raw, "mdy")
        except ValueError:
            return None


def _month_span(dates: list[date]) -> str:
    if not dates:
        return ""
    first, last = min(dates), max(dates)
    if (first.year, first.month) == (last.year, last.month):
        return first.strftime("%B %Y")
    return f"{first.strftime('%B %Y')}–{last.strftime('%B %Y')}"


def open_invoices(invoices: list[InvoiceExtract], bank: list[BankLine]) -> Iterator[Finding]:
    outs = [b for b in bank if b.direction == "out"]
    if not outs:
        return
    pay_amts = {_dec(b.amount) for b in outs}
    pay_amts.discard(None)
    bank_dates = [d for d in (_as_date(b.payment_date) for b in outs) if d]
    bank_label = _month_span(bank_dates)
    same: list[tuple[InvoiceExtract, Decimal, date | None]] = []
    other: list[tuple[InvoiceExtract, Decimal, date | None]] = []
    for inv in invoices:
        amt = _dec(inv.amount)
        if amt is None:
            continue
        if amt in pay_amts:
            continue
        inv_date = _as_date(inv.invoice_date)
        other_period = False
        if inv_date and bank_dates:
            lo, hi = min(bank_dates), max(bank_dates)
            other_period = not ((lo.year, lo.month) <= (inv_date.year, inv_date.month) <= (hi.year, hi.month))
        (other if other_period else same).append((inv, amt, inv_date))

    if len(other) >= 3:
        total = sum((amt for _, amt, _ in other), start=Decimal("0"))
        sample = other[0][2]
        sample_label = sample.strftime("%B %Y") if sample else "another month"
        yield Finding(
            amount_at_risk=total,
            currency=other[0][0].currency or "INR",
            confidence=Decimal("0.45"),
            title=(
                f"{len(other)} bills are from months outside this bank file ({bank_label}) "
                f"— other period, not necessarily unpaid"
            ),
            explanation={
                "why": (
                    "These bills and the bank statement are from different months. "
                    "This is a period gap, not proof they are unpaid."
                ),
                "count": len(other),
                "bank_period": bank_label,
                "examples": [inv.invoice_number for inv, _, _ in other[:8]],
                "sample_month": sample_label,
                "other_period": True,
                "rule": OPEN_INVOICE,
            },
            evidence={"count": len(other)},
            fingerprint_parts=[OPEN_INVOICE, "other-period", bank_label, str(len(other))],
        )
        other = []

    leftover_other = {id(inv) for inv, _, _ in other}
    for inv, amt, inv_date in other + same:
        is_other = id(inv) in leftover_other
        vendor = (inv.vendor_name or "")[:32]
        if is_other and inv_date:
            title = (
                f"{inv.invoice_number} is from {inv_date.strftime('%B %Y')}; "
                f"this bank file covers {bank_label} — other period, not necessarily unpaid"
            )
            why = (
                "The bill and the bank statement are from different months. "
                "This is a period gap, not proof the bill is unpaid. Confirm or dismiss."
            )
        else:
            title = f"{inv.invoice_number} ({vendor}) has no bank line of {amt} in this statement"
            why = (
                "Invoice captured, no equal outflow in the bank file you dropped. "
                "Confirm unpaid, other account, or other period."
            )
        yield Finding(
            amount_at_risk=amt,
            currency=inv.currency or "INR",
            confidence=Decimal("0.45") if is_other else Decimal("0.60"),
            title=title,
            explanation={
                "why": why,
                "invoice": inv.invoice_number,
                "vendor": inv.vendor_name,
                "invoice_date": inv.invoice_date,
                "bank_period": bank_label,
                "other_period": is_other,
                "rule": OPEN_INVOICE,
            },
            evidence={"invoice_number": inv.invoice_number},
            fingerprint_parts=[OPEN_INVOICE, normalise_invoice(inv.invoice_number)],
        )


def build_desk(
    invoices: list[InvoiceExtract],
    bank: list[BankLine],
    two_b: list[TwoBRow],
) -> dict[str, list[Finding]]:
    amount_hits = list(suggest_matches(invoices, bank))
    matched_nums = {
        str((f.explanation or {}).get("invoice") or "")
        for f in amount_hits
        if (f.explanation or {}).get("invoice")
    }
    opens = [f for f in open_invoices(invoices, bank) if (f.explanation or {}).get("invoice") not in matched_nums]
    return {
        DUP_DOC: list(duplicate_documents(invoices)),
        DUP_REVISED: list(revised_documents(invoices)),
        DUP_VENDOR: list(vendor_dups(invoices)),
        MATCH_SUGGEST: amount_hits + list(name_matches(invoices, bank)),
        CREDIT_UNAPPLIED: list(credit_notes(two_b)),
        AMT_2B: list(amount_vs_2b(invoices, two_b)),
        COMP_2B_MISSING: list(invoice_not_in_2b(invoices, two_b)),
        COMP_2B_ORPHAN: list(two_b_not_in_invoices(invoices, two_b, claim_complete=True)),
        OPEN_INVOICE: opens,
        OPEN_BANK: list(_open_bank_summary(bank, amount_hits)),
    }


def _open_bank_summary(bank: list[BankLine], amount_hits: list[Finding]) -> Iterator[Finding]:
    outs = [b for b in bank if b.direction == "out"]
    linked = len(amount_hits)
    leftover = max(0, len(outs) - linked)
    if leftover <= 0 or not outs:
        return
    total = sum((_dec(b.amount) or Decimal("0") for b in outs), start=Decimal("0"))
    yield Finding(
        amount_at_risk=total,
        currency="INR",
        confidence=Decimal("0.50"),
        title=f"{leftover} bank outflows (of {len(outs)}) have no captured invoice in this drop",
        explanation={
            "why": "The statement has more payments than invoices you uploaded. Other period, other account, payroll, or missing bills.",
            "bank_outflows": len(outs),
            "suggested_links": linked,
            "rule": OPEN_BANK,
        },
        evidence={"count": leftover},
        fingerprint_parts=[OPEN_BANK, str(len(outs)), str(leftover)],
    )
