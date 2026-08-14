from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser, Vendor, VendorIdentity, VendorIdentityMember
from accumo_foundation.audit import write
from accumo_foundation.auth import current_user, require_roles

router = APIRouter(prefix="/identities", tags=["identities"])


def _owned(db: Session, ident_id: uuid.UUID, user: AppUser) -> VendorIdentity:
    ident = db.get(VendorIdentity, ident_id)
    if not ident or ident.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Identity not found")
    return ident


@router.get("/pending")
def pending(
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    rows = db.scalars(
        select(VendorIdentity).where(
            VendorIdentity.organisation_id == user.organisation_id,
            VendorIdentity.method == "name_fuzzy",
            VendorIdentity.reviewed_by.is_(None),
        )
    ).all()
    out = []
    for ident in rows:
        members = db.scalars(
            select(Vendor)
            .join(VendorIdentityMember, VendorIdentityMember.vendor_id == Vendor.id)
            .where(VendorIdentityMember.identity_id == ident.id)
        ).all()
        out.append(
            {
                "id": str(ident.id),
                "canonical_name": ident.canonical_name,
                "confidence": str(ident.confidence),
                "method": ident.method,
                "members": [{"id": str(v.id), "name": v.name, "tax_id": v.tax_id} for v in members],
            }
        )
    return {"pending": out}


@router.post("/{ident_id}/confirm")
def confirm(
    ident_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    ident = _owned(db, ident_id, user)
    ident.reviewed_by = user.id
    write(
        db,
        action="identity.confirmed",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="vendor_identity",
        object_id=ident.id,
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"ok": True, "id": str(ident.id)}


@router.post("/{ident_id}/split")
def split(
    ident_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    ident = _owned(db, ident_id, user)
    members = list(db.scalars(select(VendorIdentityMember).where(VendorIdentityMember.identity_id == ident.id)))
    vendor_ids = [m.vendor_id for m in members]
    for m in members:
        db.delete(m)
    db.delete(ident)
    for vid in vendor_ids:
        v = db.get(Vendor, vid)
        if not v:
            continue
        solo = VendorIdentity(
            organisation_id=user.organisation_id,
            canonical_name=v.name,
            tax_id=v.tax_id,
            confidence=1,
            method="manual",
            reviewed_by=user.id,
        )
        db.add(solo)
        db.flush()
        db.add(VendorIdentityMember(identity_id=solo.id, vendor_id=v.id))
    write(
        db,
        action="identity.split",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="vendor_identity",
        object_id=ident_id,
        detail={"members": len(vendor_ids)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"ok": True, "split_into": len(vendor_ids)}
