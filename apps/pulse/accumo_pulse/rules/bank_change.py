"""R4 · BANK_CHANGE_PAY — vendor bank changed, then a payment went to the new account.

If we have never seen two different accounts for any vendor, the rule is
not assessable. A silent empty list is worse than saying so.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from accumo_rules.context import BankObservation, PaymentToBank
from accumo_rules.engine import Finding

CODE = "BANK_CHANGE_PAY"
DEFAULT_PARAMS = {"window_days": 30}
CONFIDENCE = Decimal("0.85")


def is_assessable(observations: list[BankObservation], payments: list[PaymentToBank]) -> bool:
    by_vendor: dict[UUID, set[str]] = defaultdict(set)
    for o in observations:
        by_vendor[o.vendor_id].add(o.account_norm)
    for p in payments:
        if p.account_norm:
            by_vendor[p.vendor_id].add(p.account_norm)
    return any(len(accs) >= 2 for accs in by_vendor.values())


class BankChangePay:
    code = CODE
    default_params = DEFAULT_PARAMS

    def run(
        self,
        payments: list[PaymentToBank],
        observations: list[BankObservation],
        params: dict | None = None,
    ) -> Iterator[Finding]:
        window = int((params or DEFAULT_PARAMS).get("window_days", 30))
        obs_by_vendor: dict[UUID, list[BankObservation]] = defaultdict(list)
        for o in observations:
            obs_by_vendor[o.vendor_id].append(o)

        # If the import only left payment.account_norm, invent observations
        # from first-seen date so a single file with two accounts still works.
        if not observations:
            first: dict[tuple[UUID, str], PaymentToBank] = {}
            for p in sorted(payments, key=lambda x: x.payment_date):
                key = (p.vendor_id, p.account_norm)
                if key not in first:
                    first[key] = p
                    obs_by_vendor[p.vendor_id].append(
                        BankObservation(
                            vendor_id=p.vendor_id,
                            vendor_identity_id=p.vendor_identity_id,
                            vendor_name=p.vendor_name,
                            account_norm=p.account_norm,
                            observed_from=p.payment_date,
                        )
                    )

        for p in payments:
            if not p.account_norm:
                continue
            rows = obs_by_vendor.get(p.vendor_id, [])
            matching = [
                o
                for o in rows
                if o.account_norm == p.account_norm and o.observed_from <= p.payment_date
            ]
            if not matching:
                continue
            current = max(matching, key=lambda o: o.observed_from)
            prior = [
                o
                for o in rows
                if o.account_norm != current.account_norm and o.observed_from < current.observed_from
            ]
            if not prior:
                continue
            gap = (p.payment_date - current.observed_from).days
            if gap < 0 or gap > window:
                continue
            yield Finding(
                amount_at_risk=p.amount.quantize(Decimal("0.0001")),
                currency=p.currency,
                confidence=CONFIDENCE,
                title=f"Paid after vendor bank account changed — {p.vendor_name}",
                explanation={
                    "rule": CODE,
                    "window_days": window,
                    "days_after_change": gap,
                    "why": "A different bank account existed for this supplier before this one. A payment went to the new account within the window.",
                    "limitation": "On a first CSV with only one account per supplier this rule cannot fire.",
                },
                evidence={
                    "payment_ids": [str(p.payment_id)],
                    "vendor_identity_id": str(p.vendor_identity_id),
                    "account_norm": p.account_norm,
                },
                fingerprint_parts=[str(p.payment_id), current.account_norm],
            )
