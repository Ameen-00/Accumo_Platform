"""Learned patterns per supplier -- the mechanism that stops Pulse asking twice.

The product rule, from the 16 Aug call with Arjun:

    Every question Pulse asks must retire a class of future questions.
    A question that only resolves one transaction is a bug.

v1 asked about each exception. Routing those same questions to more people would
not have fixed it -- it would have spread the clerical work around. Zoho already
does transaction-level matching for free; a longer list is not a product.

So a human teaches a pattern once -- "ABC Traders is paid net of 2% TDS,
narration ABCTRD, from the HDFC current account" -- and it applies to every
transaction that fits, past and future.

Two rules the rest of the codebase must respect:

1. `should_ask` is the ONLY way to decide whether to raise a question at a
   person. If it returns False, do not ask, even if this particular transaction
   is unresolved. Leave it unexplained and say so.
2. A human answer is a clue, not a fact (sheet point 32). `teach` records it and
   raises confidence; it does not stop Pulse checking the data against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable

# Pattern kinds. Adding one here is adding a class of question Pulse may ask
# exactly once per supplier.
NARRATION = "narration"        # text/beneficiary that identifies this supplier's payments
BANK_ACCOUNT = "bank_account"  # account they are normally paid from/into
TDS = "tds"                    # expected deduction by nature of work
TERMS = "terms"                # credit period read off invoices
CADENCE = "cadence"            # weekly/monthly, usual dates
CLUBBING = "clubbing"          # do several invoices normally settle together
CREDIT_ADJUST = "credit_adjust"  # how credit notes are applied

KINDS = frozenset({NARRATION, BANK_ACCOUNT, TDS, TERMS, CADENCE, CLUBBING, CREDIT_ADJUST})

TAUGHT = "taught"
OBSERVED = "observed"


@dataclass
class Pattern:
    """One learned thing about one supplier."""

    kind: str
    value: dict
    source: str = OBSERVED
    confidence: Decimal = Decimal("0.500")
    observations: int = 0
    asked_at: datetime | None = None

    @property
    def is_taught(self) -> bool:
        return self.source == TAUGHT


def by_kind(patterns: Iterable[Pattern]) -> dict[str, Pattern]:
    return {p.kind: p for p in patterns}


def should_ask(patterns: Iterable[Pattern], kind: str) -> bool:
    """May Pulse put this question to a human?

    False once the question has been asked, whether or not the answer was
    useful. Asking again is a defect -- the person already gave us their
    attention on this and we owe them a product that remembers.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown pattern kind: {kind}")
    existing = by_kind(patterns).get(kind)
    if existing is None:
        return True
    if existing.asked_at is not None:
        return False
    # Pulse worked it out on its own with enough support -- do not bother anyone.
    if existing.source == OBSERVED and existing.confidence >= Decimal("0.850"):
        return False
    return True


def merge(existing: Pattern | None, incoming: Pattern) -> Pattern:
    """Combine what Pulse observed with what a person taught.

    A taught pattern outranks an observed one, because the person has context
    the data does not carry. But a taught pattern never erases the observation
    count -- that is the evidence we check the teaching against later.
    """
    if existing is None:
        return incoming
    if existing.kind != incoming.kind:
        raise ValueError("cannot merge patterns of different kinds")

    if incoming.is_taught and not existing.is_taught:
        return Pattern(
            kind=incoming.kind,
            value=incoming.value,
            source=TAUGHT,
            confidence=max(incoming.confidence, Decimal("0.900")),
            observations=existing.observations,
            asked_at=incoming.asked_at or existing.asked_at,
        )
    if existing.is_taught and not incoming.is_taught:
        # Keep the teaching, but count the corroboration.
        return Pattern(
            kind=existing.kind,
            value=existing.value,
            source=TAUGHT,
            confidence=existing.confidence,
            observations=existing.observations + incoming.observations,
            asked_at=existing.asked_at,
        )

    # Both observed, or both taught -- newest wins, evidence accumulates.
    return Pattern(
        kind=incoming.kind,
        value=incoming.value,
        source=incoming.source,
        confidence=max(existing.confidence, incoming.confidence),
        observations=existing.observations + incoming.observations,
        asked_at=incoming.asked_at or existing.asked_at,
    )


def confidence_for(observations: int) -> Decimal:
    """How sure Pulse is from repetition alone.

    Deliberately slow. Two payments with the same narration is a coincidence;
    six is a habit. Reaching 0.850 stops Pulse asking (see should_ask), so this
    curve decides how much evidence buys silence.
    """
    if observations <= 1:
        return Decimal("0.400")
    if observations == 2:
        return Decimal("0.600")
    if observations <= 4:
        return Decimal("0.750")
    if observations <= 6:
        return Decimal("0.850")
    return Decimal("0.950")


# --------------------------------------------------------------------- TDS --
# The rate follows the NATURE OF THE WORK, not the supplier. The same supplier
# can invoice contract work at one section and professional fees at another.
# So a tds pattern stores a rate per nature, and is a prior to check -- never a
# rate to apply blindly.
#
#   value = {"by_nature": {"contract": {"section": "194C", "rate": "2.0"}}}


def tds_prior(patterns: Iterable[Pattern], nature: str) -> dict | None:
    """What Pulse expects to be deducted for this supplier doing this work.

    Returns None when nothing has been learned for that nature -- which is the
    correct answer, and must not be silently treated as "no TDS".
    """
    p = by_kind(patterns).get(TDS)
    if p is None:
        return None
    return (p.value or {}).get("by_nature", {}).get(nature)


def learn_tds(existing: Pattern | None, nature: str, section: str, rate: Decimal, taught: bool) -> Pattern:
    """Record the deduction seen (or taught) for one nature of work.

    Natures are kept separate on purpose. Learning "ABC Traders -> 2%" and
    applying it to a professional-fee invoice from the same supplier would be
    confidently wrong, which is worse than unresolved.
    """
    value = dict(existing.value) if existing and existing.value else {}
    by_nature = dict(value.get("by_nature", {}))
    by_nature[nature] = {"section": section, "rate": str(rate)}
    value["by_nature"] = by_nature

    obs = (existing.observations if existing else 0) + (0 if taught else 1)
    return Pattern(
        kind=TDS,
        value=value,
        source=TAUGHT if taught else OBSERVED,
        confidence=Decimal("0.900") if taught else confidence_for(obs),
        observations=obs,
        asked_at=existing.asked_at if existing else None,
    )
