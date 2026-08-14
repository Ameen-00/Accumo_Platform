"""R2 · DUP_FUZZY — same identity and amount, invoice numbers almost match.

Skips anything DUP_EXACT already owns (identical invoice_norm).
Skips obvious instalments and rent-like round repeats by default.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

from rapidfuzz import fuzz

from accumo_rules.context import AllocatedPayment
from accumo_rules.engine import Finding

CODE = "DUP_FUZZY"
DEFAULT_PARAMS = {
    "window_days": 90,
    "min_similarity": 85,
    "exclude_instalments": True,
    "exclude_round_repeats": True,
}
CONFIDENCE = Decimal("0.70")


def amounts_close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal("0.01"), (a * Decimal("0.001")).copy_abs())


class DupFuzzy:
    code = CODE
    default_params = DEFAULT_PARAMS

    def run(self, payments: list[AllocatedPayment], params: dict | None = None) -> Iterator[Finding]:
        p = {**DEFAULT_PARAMS, **(params or {})}
        window = int(p["window_days"])
        min_sim = int(p["min_similarity"])
        skip_inst = bool(p["exclude_instalments"])
        skip_round = bool(p["exclude_round_repeats"])

        by_ident: dict = defaultdict(list)
        for row in payments:
            by_ident[row.vendor_identity_id].append(row)

        seen: set[tuple] = set()
        for ident, rows in by_ident.items():
            if skip_round and _mostly_round_repeats(rows):
                continue
            rows = sorted(rows, key=lambda r: r.payment_date)
            for i, a in enumerate(rows):
                for b in rows[i + 1 :]:
                    if (b.payment_date - a.payment_date).days > window:
                        break
                    if a.currency != b.currency:
                        continue
                    if a.invoice_norm == b.invoice_norm:
                        continue
                    if not amounts_close(a.amount, b.amount):
                        continue
                    if skip_inst and _looks_like_instalment(a, b):
                        continue
                    score = fuzz.ratio(a.invoice_norm, b.invoice_norm)
                    if score < min_sim:
                        continue
                    pair = tuple(sorted((str(a.payment_id), str(b.payment_id))))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    yield _finding(a, b, ident, score, window)


def _finding(a: AllocatedPayment, b: AllocatedPayment, ident, score: int, window: int) -> Finding:
    extra = min(a.amount, b.amount)
    pay_ids = sorted([str(a.payment_id), str(b.payment_id)])
    inv_ids = sorted({str(a.invoice_id), str(b.invoice_id)})
    return Finding(
        amount_at_risk=extra.quantize(Decimal("0.0001")),
        currency=a.currency,
        confidence=CONFIDENCE,
        title=f"Probably the same invoice paid twice — {a.vendor_name}",
        explanation={
            "rule": CODE,
            "invoices": [a.invoice_number, b.invoice_number],
            "similarity": score,
            "amount": str(a.amount),
            "window_days": window,
            "why": "Same supplier, same amount, invoice numbers almost match, not an exact duplicate.",
        },
        evidence={
            "payment_ids": pay_ids,
            "invoice_ids": inv_ids,
            "vendor_identity_id": str(ident),
        },
        fingerprint_parts=pay_ids + inv_ids,
    )


def _looks_like_instalment(a: AllocatedPayment, b: AllocatedPayment) -> bool:
    gap = abs((b.payment_date - a.payment_date).days)
    return 28 <= gap <= 33 and amounts_close(a.amount, b.amount)


def _mostly_round_repeats(rows: list[AllocatedPayment]) -> bool:
    if len(rows) < 4:
        return False
    amounts = [r.amount for r in rows]
    mode = max(set(amounts), key=amounts.count)
    if int(mode) % 1000 != 0:
        return False
    return amounts.count(mode) / len(amounts) >= 0.7
