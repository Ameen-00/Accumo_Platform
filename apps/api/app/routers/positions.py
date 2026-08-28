"""Supplier positions -- the landing screen that replaces the exception queue.

From the 16 Aug call: a screen that says match, match, match is "just another
clerical reconciliation", and Zoho already reaches that stage without AI. So the
first thing anyone sees is one row per supplier, and the exceptions become the
evidence behind a row rather than the product.

There is no confirm/dismiss here on purpose. A position is computed from
documents; it is not something a person signs off.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import (
    AppUser,
    CreditNote,
    Invoice,
    Payment,
    PaymentAllocation,
    SupplierPattern,
    Vendor,
    VendorIdentity,
    VendorIdentityMember,
)
from accumo_canonical.models import Exception as ExceptionRow
from accumo_foundation.auth import current_user
from accumo_rules.desk import AMT_2B, COMP_2B_MISSING, COMP_2B_ORPHAN
from accumo_rules.position import SupplierInput, summarise

router = APIRouter(prefix="/positions", tags=["positions"])

ZERO = Decimal("0")
GST_RULES = (COMP_2B_MISSING, COMP_2B_ORPHAN, AMT_2B)


def _org(user: AppUser) -> uuid.UUID:
    if not user.organisation_id:
        raise HTTPException(status_code=404, detail="No organisation for this user.")
    return user.organisation_id


def _identity_map(db: Session, org: uuid.UUID) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    """vendor_id -> (grouping key, display name).

    Where identity resolution has merged several vendor rows into one real
    party, the identity is the key. Where it has not run or found nothing, the
    vendor stands alone rather than being dropped -- a supplier missing from the
    landing screen is worse than one shown unmerged.
    """
    out: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}

    rows = db.execute(
        select(VendorIdentityMember.vendor_id, VendorIdentity.id, VendorIdentity.canonical_name)
        .join(VendorIdentity, VendorIdentity.id == VendorIdentityMember.identity_id)
        .where(VendorIdentity.organisation_id == org)
    ).all()
    for vendor_id, identity_id, name in rows:
        out[vendor_id] = (identity_id, name)

    for vendor_id, name in db.execute(
        select(Vendor.id, Vendor.name).where(Vendor.organisation_id == org)
    ).all():
        out.setdefault(vendor_id, (vendor_id, name))

    return out


def _collect(db: Session, org: uuid.UUID) -> list[SupplierInput]:
    ident = _identity_map(db, org)
    if not ident:
        return []

    acc: dict[uuid.UUID, SupplierInput] = {}

    def slot(vendor_id: uuid.UUID | None) -> SupplierInput | None:
        if vendor_id is None or vendor_id not in ident:
            return None
        key, name = ident[vendor_id]
        if key not in acc:
            acc[key] = SupplierInput(identity_id=key, name=name)
        return acc[key]

    for vendor_id, total, n, ccy in db.execute(
        select(Invoice.vendor_id, func.sum(Invoice.gross_amount), func.count(), func.min(Invoice.currency))
        .where(Invoice.organisation_id == org)
        .group_by(Invoice.vendor_id)
    ).all():
        s = slot(vendor_id)
        if s:
            s.invoiced += total or ZERO
            s.invoice_count += n
            s.currency = ccy or s.currency

    for vendor_id, total, n in db.execute(
        select(Payment.vendor_id, func.sum(Payment.amount), func.count())
        .where(Payment.organisation_id == org)
        .group_by(Payment.vendor_id)
    ).all():
        s = slot(vendor_id)
        if s:
            s.paid += total or ZERO
            s.payment_count += n

    for vendor_id, total in db.execute(
        select(CreditNote.vendor_id, func.sum(CreditNote.amount))
        .where(CreditNote.organisation_id == org)
        .group_by(CreditNote.vendor_id)
    ).all():
        s = slot(vendor_id)
        if s:
            s.credit_notes += total or ZERO

    # A payment is "explained" when Pulse tied it to at least one invoice.
    for vendor_id, n in db.execute(
        select(Payment.vendor_id, func.count(func.distinct(Payment.id)))
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .where(Payment.organisation_id == org)
        .group_by(Payment.vendor_id)
    ).all():
        s = slot(vendor_id)
        if s:
            s.explained_payments += n

    # GST sits on the exception rows rather than the ledger, because it comes
    # from GSTR-2B rather than from the books.
    for identity_id, total in db.execute(
        select(ExceptionRow.vendor_identity_id, func.sum(ExceptionRow.amount_at_risk))
        .where(
            ExceptionRow.organisation_id == org,
            ExceptionRow.rule_code.in_(GST_RULES),
            ExceptionRow.vendor_identity_id.isnot(None),
        )
        .group_by(ExceptionRow.vendor_identity_id)
    ).all():
        if identity_id in acc:
            acc[identity_id].gst_difference += total or ZERO

    # Waiting = a question has gone to a person and no answer has come back.
    # asked_at set while the pattern is still only observed means exactly that.
    for identity_id, n in db.execute(
        select(SupplierPattern.identity_id, func.count())
        .where(
            SupplierPattern.organisation_id == org,
            SupplierPattern.asked_at.isnot(None),
            SupplierPattern.source == "observed",
        )
        .group_by(SupplierPattern.identity_id)
    ).all():
        if identity_id in acc:
            acc[identity_id].open_questions += n

    return list(acc.values())


@router.get("")
def list_positions(
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    org = _org(user)
    summary = summarise(_collect(db, org))
    return {
        "headline": summary.headline,
        "checked": summary.checked,
        "clear": summary.clear,
        "differences": summary.differences,
        "waiting": summary.waiting,
        "positions": [
            {
                "identity_id": str(p.identity_id),
                "name": p.name,
                "currency": p.currency,
                "headline": p.headline,
                "state": p.state,
                "invoiced": str(p.invoiced),
                "paid": str(p.paid),
                "credit_notes": str(p.credit_notes),
                "difference": str(p.difference),
                "gst_difference": str(p.gst_difference),
                "invoice_count": p.invoice_count,
                "payment_count": p.payment_count,
                "unexplained_payments": p.unexplained_payments,
                "open_questions": p.open_questions,
                "waiting_on": p.waiting_on,
            }
            for p in summary.positions
        ],
    }


@router.get("/{identity_id}")
def position_detail(
    identity_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    """Everything behind one row. This is where transactions appear -- and only
    here, after someone asked for them."""
    org = _org(user)

    ident = _identity_map(db, org)
    vendor_ids = [v for v, (key, _) in ident.items() if key == identity_id]
    if not vendor_ids:
        raise HTTPException(status_code=404, detail="Supplier not found")

    position = next(
        (p for p in summarise(_collect(db, org)).positions if p.identity_id == identity_id),
        None,
    )
    if position is None:
        raise HTTPException(status_code=404, detail="Supplier not found")

    invoices = db.execute(
        select(Invoice.invoice_number, Invoice.invoice_date, Invoice.gross_amount, Invoice.currency)
        .where(Invoice.organisation_id == org, Invoice.vendor_id.in_(vendor_ids))
        .order_by(Invoice.invoice_date.desc().nullslast())
        .limit(200)
    ).all()

    payments = db.execute(
        select(Payment.payment_date, Payment.amount, Payment.currency, Payment.reference)
        .where(Payment.organisation_id == org, Payment.vendor_id.in_(vendor_ids))
        .order_by(Payment.payment_date.desc())
        .limit(200)
    ).all()

    credits = db.execute(
        select(CreditNote.source_ref, CreditNote.note_date, CreditNote.amount, CreditNote.applied)
        .where(CreditNote.organisation_id == org, CreditNote.vendor_id.in_(vendor_ids))
        .order_by(CreditNote.note_date.desc().nullslast())
        .limit(100)
    ).all()

    return {
        "identity_id": str(identity_id),
        "name": position.name,
        "currency": position.currency,
        "headline": position.headline,
        "state": position.state,
        "invoiced": str(position.invoiced),
        "paid": str(position.paid),
        "credit_notes": str(position.credit_notes),
        "difference": str(position.difference),
        "gst_difference": str(position.gst_difference),
        "unexplained_payments": position.unexplained_payments,
        "invoices": [
            {"number": n, "date": d.isoformat() if d else None, "amount": str(a), "currency": c}
            for n, d, a, c in invoices
        ],
        "payments": [
            {"date": d.isoformat() if d else None, "amount": str(a), "currency": c, "reference": r}
            for d, a, c, r in payments
        ],
        "credit_notes_list": [
            {"ref": r, "date": d.isoformat() if d else None, "amount": str(a), "applied": bool(ap)}
            for r, d, a, ap in credits
        ],
    }
