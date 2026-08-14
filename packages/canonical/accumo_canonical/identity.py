"""Link vendor rows into real-world parties.

Auto-merge only at confidence >= 0.85.
Fuzzy name matches go to a human queue. A wrong merge looks like
duplicate payments that are not duplicates — that kills trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from rapidfuzz import fuzz

AUTO_MIN = Decimal("0.85")
FUZZY_MIN = 88

METHODS = (
    ("tax_id", Decimal("1.00")),
    ("bank", Decimal("0.95")),
    ("registration_id", Decimal("0.95")),
    ("name_exact", Decimal("0.85")),
)


@dataclass
class VendorSnap:
    id: UUID
    name: str
    name_normalised: str
    tax_id: str | None
    registration_id: str | None
    account_norms: list[str] = field(default_factory=list)


@dataclass
class ProposedIdentity:
    member_ids: list[UUID]
    method: str
    confidence: Decimal
    canonical_name: str
    tax_id: str | None
    needs_review: bool


class _UF:
    def __init__(self, ids: list[UUID]) -> None:
        self.parent = {i: i for i in ids}
        self.why: dict[tuple[UUID, UUID], tuple[str, Decimal]] = {}

    def find(self, x: UUID) -> UUID:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: UUID, b: UUID, method: str, confidence: Decimal) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        self.parent[rb] = ra
        self.why[(ra, rb)] = (method, confidence)


def _group_key(vendors: list[VendorSnap], attr: str) -> dict[str, list[VendorSnap]]:
    buckets: dict[str, list[VendorSnap]] = {}
    for v in vendors:
        raw = getattr(v, attr)
        if not raw:
            continue
        buckets.setdefault(str(raw), []).append(v)
    return buckets


def propose(vendors: list[VendorSnap]) -> list[ProposedIdentity]:
    if not vendors:
        return []
    uf = _UF([v.id for v in vendors])
    by_id = {v.id: v for v in vendors}

    def merge_buckets(buckets: dict[str, list[VendorSnap]], method: str, confidence: Decimal) -> None:
        for group in buckets.values():
            if len(group) < 2:
                continue
            head = group[0]
            for other in group[1:]:
                uf.union(head.id, other.id, method, confidence)

    merge_buckets(_group_key(vendors, "tax_id"), "tax_id", Decimal("1.00"))
    bank_buckets: dict[str, list[VendorSnap]] = {}
    for v in vendors:
        for acc in v.account_norms:
            if acc:
                bank_buckets.setdefault(acc, []).append(v)
    merge_buckets(bank_buckets, "bank", Decimal("0.95"))
    merge_buckets(_group_key(vendors, "registration_id"), "registration_id", Decimal("0.95"))
    merge_buckets(_group_key(vendors, "name_normalised"), "name_exact", Decimal("0.85"))

    clusters: dict[UUID, list[VendorSnap]] = {}
    for v in vendors:
        clusters.setdefault(uf.find(v.id), []).append(v)

    used: set[UUID] = set()
    out: list[ProposedIdentity] = []

    for members in clusters.values():
        if len(members) == 1:
            continue
        method, confidence = _strongest(members, uf)
        out.append(_proposal(members, method, confidence, needs_review=False))
        used.update(m.id for m in members)

    leftovers = [v for v in vendors if v.id not in used]
    claimed: set[UUID] = set()
    for i, a in enumerate(leftovers):
        if a.id in claimed or not a.name_normalised:
            continue
        for b in leftovers[i + 1 :]:
            if b.id in claimed or not b.name_normalised:
                continue
            score = fuzz.token_sort_ratio(a.name_normalised, b.name_normalised)
            if score < FUZZY_MIN:
                continue
            # Map 88–100 onto 0.60–0.84 so it never auto-merges.
            conf = Decimal("0.60") + (Decimal(score - FUZZY_MIN) / Decimal(100 - FUZZY_MIN)) * Decimal("0.24")
            if conf >= AUTO_MIN:
                conf = Decimal("0.84")
            out.append(_proposal([a, b], "name_fuzzy", conf.quantize(Decimal("0.001")), needs_review=True))
            claimed.add(a.id)
            claimed.add(b.id)
            used.add(a.id)
            used.add(b.id)
            break

    for v in vendors:
        if v.id in used:
            continue
        out.append(_proposal([v], "name_exact", Decimal("1.00"), needs_review=False))

    return out


def _strongest(members: list[VendorSnap], uf: _UF) -> tuple[str, Decimal]:
    best_method, best_conf = "name_exact", Decimal("0.85")
    for (_a, _b), (method, conf) in uf.why.items():
        if conf > best_conf:
            best_method, best_conf = method, conf
    # Re-derive from data so we do not depend on UF edge bookkeeping.
    if _shared(members, "tax_id"):
        return "tax_id", Decimal("1.00")
    if _shared_banks(members):
        return "bank", Decimal("0.95")
    if _shared(members, "registration_id"):
        return "registration_id", Decimal("0.95")
    if _shared(members, "name_normalised"):
        return "name_exact", Decimal("0.85")
    return best_method, best_conf


def _shared(members: list[VendorSnap], attr: str) -> bool:
    values = {getattr(m, attr) for m in members if getattr(m, attr)}
    return len(values) == 1 and len(members) > 1


def _shared_banks(members: list[VendorSnap]) -> bool:
    seen: set[str] = set()
    for m in members:
        for acc in m.account_norms:
            if acc in seen:
                return True
            seen.add(acc)
    return False


def _proposal(members: list[VendorSnap], method: str, confidence: Decimal, needs_review: bool) -> ProposedIdentity:
    named = sorted(members, key=lambda m: m.name)
    tax = next((m.tax_id for m in named if m.tax_id), None)
    return ProposedIdentity(
        member_ids=[m.id for m in named],
        method=method,
        confidence=confidence,
        canonical_name=named[0].name,
        tax_id=tax,
        needs_review=needs_review,
    )
