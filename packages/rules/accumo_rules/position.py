"""Supplier position -- what the owner sees instead of an exception queue.

From the 16 Aug call: a screen that says match, match, match is "just another
clerical reconciliation", and Zoho reaches that stage without AI. So the landing
screen is one row per supplier, and the exceptions become the evidence behind a
row rather than the product itself.

    40 suppliers checked -> 35 clear -> 3 differences -> 2 waiting on information

    ABC Traders        Rs 52,000 difference       2 questions open
    XYZ Agencies       Rs 28,000 GST difference   waiting on Rajesh
    Southern Steels    clear

Deliberately not here: any notion of "confirm this row". A position is a fact
computed from documents, not something a person signs off. The only human input
is teaching a pattern once, or handing over a document -- see patterns.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable
from uuid import UUID

ZERO = Decimal("0")

CLEAR = "clear"
DIFFERENCE = "difference"
WAITING = "waiting"

# Below this, a difference is rounding or a part-payment in flight, not a
# finding. Showing an owner a Rs 3 difference costs more trust than it earns.
MATERIAL = Decimal("100")


@dataclass
class SupplierInput:
    """Everything known about one supplier for the period, already resolved to
    a single identity (see canonical/resolve.py)."""

    identity_id: UUID
    name: str
    currency: str = "INR"
    invoiced: Decimal = ZERO
    paid: Decimal = ZERO
    credit_notes: Decimal = ZERO
    invoice_count: int = 0
    payment_count: int = 0
    # Payments Pulse could tie to one or more invoices.
    explained_payments: int = 0
    # Questions genuinely outstanding with a person -- retrieval or one-time
    # teaching only. Never "please reconcile this".
    open_questions: int = 0
    waiting_on: str | None = None
    gst_difference: Decimal = ZERO


@dataclass
class SupplierPosition:
    identity_id: UUID
    name: str
    currency: str
    invoiced: Decimal
    paid: Decimal
    credit_notes: Decimal
    difference: Decimal
    invoice_count: int
    payment_count: int
    explained_payments: int
    unexplained_payments: int
    gst_difference: Decimal
    open_questions: int
    waiting_on: str | None
    state: str

    @property
    def headline(self) -> str:
        """One line, in the words an owner uses. No rule codes, no percentages."""
        if self.state == CLEAR:
            return "clear"
        if self.state == WAITING:
            who = f" on {self.waiting_on}" if self.waiting_on else ""
            return f"waiting{who}"
        parts = []
        if abs(self.difference) >= MATERIAL:
            parts.append(f"{self.currency} {abs(self.difference):,.0f} difference")
        if abs(self.gst_difference) >= MATERIAL:
            parts.append(f"{self.currency} {abs(self.gst_difference):,.0f} GST difference")
        return " · ".join(parts) or "difference"


@dataclass
class PositionSummary:
    checked: int
    clear: int
    differences: int
    waiting: int
    positions: list[SupplierPosition] = field(default_factory=list)

    @property
    def headline(self) -> str:
        return (
            f"{self.checked} suppliers checked -> {self.clear} clear -> "
            f"{self.differences} differences -> {self.waiting} waiting on information"
        )


def position_for(src: SupplierInput) -> SupplierPosition:
    """Compute one supplier's position.

    Order of precedence matters. A supplier with an open question is *waiting*,
    not *difference*, even when the numbers do not tie -- because the honest
    statement is "I have asked someone and not heard back", not "you are short
    Rs 52,000". Claiming a difference we already know the reason for is the kind
    of confident wrongness that loses an owner's trust in one screen.
    """
    difference = src.invoiced - src.credit_notes - src.paid
    unexplained = max(0, src.payment_count - src.explained_payments)

    if src.open_questions > 0:
        state = WAITING
    elif abs(difference) >= MATERIAL or abs(src.gst_difference) >= MATERIAL or unexplained > 0:
        state = DIFFERENCE
    else:
        state = CLEAR

    return SupplierPosition(
        identity_id=src.identity_id,
        name=src.name,
        currency=src.currency,
        invoiced=src.invoiced,
        paid=src.paid,
        credit_notes=src.credit_notes,
        difference=difference,
        invoice_count=src.invoice_count,
        payment_count=src.payment_count,
        explained_payments=src.explained_payments,
        unexplained_payments=unexplained,
        gst_difference=src.gst_difference,
        open_questions=src.open_questions,
        waiting_on=src.waiting_on,
        state=state,
    )


def summarise(sources: Iterable[SupplierInput]) -> PositionSummary:
    """Build the landing screen.

    Sorted so the money is at the top: differences first by size, then waiting,
    then clear. An owner should never scroll to find the problem.
    """
    positions = [position_for(s) for s in sources]

    order = {DIFFERENCE: 0, WAITING: 1, CLEAR: 2}
    positions.sort(
        key=lambda p: (
            order[p.state],
            -(abs(p.difference) + abs(p.gst_difference)),
            p.name.lower(),
        )
    )

    return PositionSummary(
        checked=len(positions),
        clear=sum(1 for p in positions if p.state == CLEAR),
        differences=sum(1 for p in positions if p.state == DIFFERENCE),
        waiting=sum(1 for p in positions if p.state == WAITING),
        positions=positions,
    )
