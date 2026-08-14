"""Exception state machine. Dismissal always needs a reason.

new ──► in_review ──► confirmed ──► recovered
  │          │
  └──────────┴────► dismissed
"""

from __future__ import annotations

from decimal import Decimal

ALLOWED: dict[str, frozenset[str]] = {
    "new": frozenset({"in_review", "dismissed"}),
    "in_review": frozenset({"confirmed", "dismissed"}),
    "confirmed": frozenset({"recovered"}),
    "dismissed": frozenset(),
    "recovered": frozenset(),
}

STATUSES = frozenset(ALLOWED)


class TransitionError(ValueError):
    pass


def assert_transition(
    current: str,
    target: str,
    reason: str | None = None,
    recovered_amount: Decimal | None = None,
) -> None:
    if current not in STATUSES:
        raise TransitionError(f"unknown status {current}")
    if target not in STATUSES:
        raise TransitionError(f"unknown status {target}")
    if target not in ALLOWED[current]:
        raise TransitionError(f"cannot move from {current} to {target}")
    if target == "dismissed" and not (reason or "").strip():
        raise TransitionError("dismissal requires a reason")
    if target == "recovered" and recovered_amount is None:
        raise TransitionError("recovery requires an amount")
    if target == "recovered" and recovered_amount is not None and recovered_amount < 0:
        raise TransitionError("recovery amount cannot be negative")
