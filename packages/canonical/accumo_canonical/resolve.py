"""Persist identity proposals for one organisation. Safe to run after each import."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.identity import VendorSnap, propose
from accumo_canonical.models import Vendor, VendorBankAccount, VendorIdentity, VendorIdentityMember


def _already_assigned(db: Session, org_id: uuid.UUID) -> set[uuid.UUID]:
    rows = db.scalars(
        select(VendorIdentityMember.vendor_id)
        .join(VendorIdentity, VendorIdentity.id == VendorIdentityMember.identity_id)
        .where(VendorIdentity.organisation_id == org_id)
    )
    return set(rows)


def _snap(db: Session, vendors: list[Vendor]) -> list[VendorSnap]:
    if not vendors:
        return []
    ids = [v.id for v in vendors]
    banks = db.scalars(select(VendorBankAccount).where(VendorBankAccount.vendor_id.in_(ids))).all()
    by_vendor: dict[uuid.UUID, list[str]] = {v.id: [] for v in vendors}
    for b in banks:
        if b.account_norm:
            by_vendor[b.vendor_id].append(b.account_norm)
    return [
        VendorSnap(
            id=v.id,
            name=v.name,
            name_normalised=v.name_normalised,
            tax_id=v.tax_id,
            registration_id=v.registration_id,
            account_norms=by_vendor[v.id],
        )
        for v in vendors
    ]


def resolve_new_vendors(db: Session, organisation_id: uuid.UUID) -> dict[str, int]:
    assigned = _already_assigned(db, organisation_id)
    vendors = [
        v
        for v in db.scalars(select(Vendor).where(Vendor.organisation_id == organisation_id))
        if v.id not in assigned
    ]
    proposals = propose(_snap(db, vendors))
    auto = pending = 0
    for p in proposals:
        ident = VendorIdentity(
            organisation_id=organisation_id,
            canonical_name=p.canonical_name,
            tax_id=p.tax_id,
            confidence=p.confidence,
            method=p.method,
            reviewed_by=None,
        )
        db.add(ident)
        db.flush()
        for vid in p.member_ids:
            db.add(VendorIdentityMember(identity_id=ident.id, vendor_id=vid))
        if p.needs_review:
            pending += 1
        else:
            auto += 1
    return {"auto": auto, "pending_review": pending, "vendors": len(vendors)}
