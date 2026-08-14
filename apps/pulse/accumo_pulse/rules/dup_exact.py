"""R1 · DUP_EXACT — same identity, same invoice, same amount, paid more than once."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

from accumo_rules.context import AllocatedPayment
from accumo_rules.engine import Finding
from accumo_rules.fingerprint import fingerprint

CODE = "DUP_EXACT"
DEFAULT_PARAMS = {"window_days": 365}
CONFIDENCE = Decimal("0.95")


class DupExact:
    code = CODE
    default_params = DEFAULT_PARAMS

    def run(self, payments: list[AllocatedPayment], params: dict | None = None) -> Iterator[Finding]:
        window = int((params or DEFAULT_PARAMS).get("window_days", 365))
        groups: dict[tuple, list[AllocatedPayment]] = defaultdict(list)
        for p in payments:
            groups[(p.vendor_identity_id, p.invoice_norm, p.amount, p.currency)].append(p)

        for (ident, inv_norm, amount, currency), rows in groups.items():
            unique: dict = {}
            for p in rows:
                unique[p.payment_id] = p
            members = sorted(unique.values(), key=lambda p: p.payment_date)
            if len(members) < 2:
                continue
            cluster = _within_window(members, window)
            if len(cluster) < 2:
                continue
            extras = len(cluster) - 1
            pay_ids = [str(p.payment_id) for p in cluster]
            inv_ids = sorted({str(p.invoice_id) for p in cluster})
            yield Finding(
                amount_at_risk=(amount * extras).quantize(Decimal("0.0001")),
                currency=currency,
                confidence=CONFIDENCE,
                title=f"Same invoice paid {len(cluster)} times — {cluster[0].vendor_name}",
                explanation={
                    "rule": CODE,
                    "invoice": cluster[0].invoice_number,
                    "invoice_norm": inv_norm,
                    "amount": str(amount),
                    "payments": len(cluster),
                    "window_days": window,
                    "why": "Same supplier identity, same invoice number, same amount, more than one payment.",
                },
                evidence={
                    "payment_ids": pay_ids,
                    "invoice_ids": inv_ids,
                    "vendor_identity_id": str(ident),
                },
                fingerprint_parts=pay_ids + inv_ids,
            )


def finding_fingerprint(finding: Finding) -> str:
    return fingerprint(CODE, *finding.fingerprint_parts)


def _within_window(members: list[AllocatedPayment], window_days: int) -> list[AllocatedPayment]:
    best: list[AllocatedPayment] = []
    for i, start in enumerate(members):
        end = start.payment_date + timedelta(days=window_days)
        chunk = [p for p in members[i:] if p.payment_date <= end]
        if len(chunk) > len(best):
            best = chunk
    return best
