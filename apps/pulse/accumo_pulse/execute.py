"""Load allocated payments for a batch and run Pulse rules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.models import (
    Invoice,
    Payment,
    PaymentAllocation,
    VendorIdentity,
    VendorIdentityMember,
)
from accumo_pulse.rules.dup_exact import DupExact
from accumo_rules.context import AllocatedPayment
from accumo_rules.persist import persist_findings


def load_allocated(db: Session, organisation_id: uuid.UUID, batch_id: uuid.UUID) -> list[AllocatedPayment]:
    stmt = (
        select(
            Payment.id,
            Invoice.id,
            Invoice.invoice_norm,
            Invoice.invoice_number,
            Payment.amount,
            Payment.currency,
            Payment.payment_date,
            VendorIdentity.id,
            VendorIdentity.canonical_name,
        )
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
        .join(VendorIdentityMember, VendorIdentityMember.vendor_id == Payment.vendor_id)
        .join(VendorIdentity, VendorIdentity.id == VendorIdentityMember.identity_id)
        .where(Payment.organisation_id == organisation_id, Payment.batch_id == batch_id)
    )
    rows = db.execute(stmt).all()
    return [
        AllocatedPayment(
            payment_id=r[0],
            invoice_id=r[1],
            invoice_norm=r[2],
            invoice_number=r[3],
            amount=r[4],
            currency=r[5],
            payment_date=r[6],
            vendor_identity_id=r[7],
            vendor_name=r[8],
        )
        for r in rows
    ]


def run_dup_exact(db: Session, organisation_id: uuid.UUID, batch_id: uuid.UUID):
    payments = load_allocated(db, organisation_id, batch_id)
    findings = list(DupExact().run(payments))
    return persist_findings(
        db,
        organisation_id=organisation_id,
        batch_id=batch_id,
        rule_code=DupExact.code,
        findings=findings,
    )
