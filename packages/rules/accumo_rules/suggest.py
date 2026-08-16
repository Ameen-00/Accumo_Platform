"""Suggest invoice ↔ bank links. Never allocate. A human must confirm."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation

import re
from datetime import date

from rapidfuzz import fuzz

from accumo_canonical.normalise import normalise_invoice, normalise_name
from accumo_ingest.bank_statement import BankLine
from accumo_ingest.invoice_pdf import InvoiceExtract
from accumo_ingest.values import parse_date
from accumo_rules.engine import Finding

MATCH_SUGGEST = "MATCH_SUGGEST"
DUP_DOC = "DUP_DOC"
DUP_REVISED = "DUP_REVISED"

_REV_HINT = re.compile(r"\b(revis|estimat|correct|amend|supplement|extra work)\b", re.I)


def _dec(raw: str) -> Decimal | None:
    try:
        return Decimal(str(raw).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError):
        return None


def duplicate_documents(invoices: list[InvoiceExtract]) -> Iterator[Finding]:
    groups: dict[str, list[InvoiceExtract]] = defaultdict(list)
    for inv in invoices:
        key = normalise_invoice(inv.invoice_number or "")
        if key:
            groups[key].append(inv)
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        amt = _dec(rows[0].amount) or Decimal("0")
        yield Finding(
            amount_at_risk=amt,
            currency=rows[0].currency or "INR",
            confidence=Decimal("0.90"),
            title=f"{rows[0].invoice_number} arrived {len(rows)} times — same invoice, two files",
            explanation={
                "why": "Two documents produced the same invoice number. Confirm it is a copy, not a second bill.",
                "invoice": rows[0].invoice_number,
                "copies": len(rows),
                "rule": DUP_DOC,
            },
            evidence={"invoice_number": rows[0].invoice_number},
            fingerprint_parts=[DUP_DOC, key],
        )


def _inv_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return parse_date(raw, "dmy")
    except ValueError:
        return None


def _looks_like_revision(a: InvoiceExtract, b: InvoiceExtract) -> bool:
    na = normalise_invoice(a.invoice_number)
    nb = normalise_invoice(b.invoice_number)
    if not na or not nb or na == nb:
        return False
    if fuzz.ratio(na, nb) >= 85:
        return True
    blob = " ".join(
        [
            a.invoice_number,
            b.invoice_number,
            a.raw_text or "",
            b.raw_text or "",
            a.po_ref or "",
            b.po_ref or "",
        ]
    )
    return bool(_REV_HINT.search(blob))


def revised_documents(invoices: list[InvoiceExtract]) -> Iterator[Finding]:
    """Same vendor, same rupees, new document — the Ernakulam ₹38,000 shape.

    Not 'same invoice number twice'. A human still confirms.
    Monthly retainers with unrelated numbers are left alone.
    """
    by_vendor: dict[str, list[InvoiceExtract]] = defaultdict(list)
    for inv in invoices:
        vendor = normalise_name(inv.vendor_name)
        if vendor and inv.invoice_number:
            by_vendor[vendor].append(inv)
    seen: set[tuple[str, str]] = set()
    for vendor, rows in by_vendor.items():
        for i, a in enumerate(rows):
            amt = _dec(a.amount)
            if amt is None or amt <= 0:
                continue
            da = _inv_date(a.invoice_date)
            for b in rows[i + 1 :]:
                if _dec(b.amount) != amt:
                    continue
                if normalise_invoice(a.invoice_number) == normalise_invoice(b.invoice_number):
                    continue
                if not _looks_like_revision(a, b):
                    continue
                db = _inv_date(b.invoice_date)
                if da and db and abs((da - db).days) > 90:
                    continue
                pair = tuple(sorted((normalise_invoice(a.invoice_number), normalise_invoice(b.invoice_number))))
                if pair in seen:
                    continue
                seen.add(pair)
                yield Finding(
                    amount_at_risk=amt,
                    currency=a.currency or "INR",
                    confidence=Decimal("0.65"),
                    title=(
                        f"{a.invoice_number} and {b.invoice_number} are both {amt} from "
                        f"{(a.vendor_name or '')[:32]} — possible revised bill paid twice. Confirm."
                    ),
                    explanation={
                        "why": (
                            "Same supplier, same rupees, two different documents. "
                            "This is how a revised estimate gets paid on top of the original. Confirm or dismiss."
                        ),
                        "invoices": [a.invoice_number, b.invoice_number],
                        "vendor": a.vendor_name,
                        "invoice_dates": [a.invoice_date, b.invoice_date],
                        "rule": DUP_REVISED,
                    },
                    evidence={"invoice_number": a.invoice_number},
                    fingerprint_parts=[DUP_REVISED, vendor, pair[0], pair[1], str(amt)],
                )


def suggest_matches(invoices: list[InvoiceExtract], bank: list[BankLine]) -> Iterator[Finding]:
    outs = [b for b in bank if b.direction == "out"]
    used: set[int] = set()
    for inv in invoices:
        amt = _dec(inv.amount)
        if amt is None or amt <= 0:
            continue
        hits: list[tuple[int, BankLine]] = []
        for i, line in enumerate(outs):
            if i in used:
                continue
            pay = _dec(line.amount)
            if pay is None or pay != amt:
                continue
            hits.append((i, line))
        if not hits:
            continue
        if len(hits) == 1:
            i, line = hits[0]
            used.add(i)
            yield Finding(
                amount_at_risk=amt,
                currency=inv.currency or "INR",
                confidence=Decimal("0.70"),
                title=f"Bank paid {amt} — possible settlement of {inv.invoice_number}. Confirm.",
                explanation={
                    "why": "Same rupee amount on a bank outflow and an invoice. Narration was not an invoice number, so Pulse will not book this.",
                    "invoice": inv.invoice_number,
                    "vendor": inv.vendor_name,
                    "narration": line.narration,
                    "payment_date": line.payment_date,
                    "invoice_date": inv.invoice_date,
                    "rule": MATCH_SUGGEST,
                },
                evidence={"invoice_number": inv.invoice_number, "payment_ref": line.reference},
                fingerprint_parts=[MATCH_SUGGEST, normalise_invoice(inv.invoice_number), line.reference or line.narration[:40]],
            )
            continue
        yield Finding(
            amount_at_risk=amt,
            currency=inv.currency or "INR",
            confidence=Decimal("0.40"),
            title=f"{len(hits)} bank lines equal {inv.invoice_number} ({amt}). Needs a human.",
            explanation={
                "why": "Several outflows share this invoice amount. Do not guess which one paid it.",
                "invoice": inv.invoice_number,
                "invoice_date": inv.invoice_date or "",
                "candidates": [h[1].narration[:80] for h in hits[:5]],
                "rule": MATCH_SUGGEST,
            },
            evidence={"invoice_number": inv.invoice_number},
            fingerprint_parts=[MATCH_SUGGEST, "multi", normalise_invoice(inv.invoice_number), str(amt)],
        )
