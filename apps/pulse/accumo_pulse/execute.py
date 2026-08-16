"""Load allocated payments for a batch and run Pulse rules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.models import (
    Invoice,
    Payment,
    PaymentAllocation,
    VendorBankAccount,
    VendorIdentity,
    VendorIdentityMember,
)
from accumo_pulse.rules.bank_change import BankChangePay, is_assessable
from accumo_pulse.rules.dup_exact import DupExact
from accumo_pulse.rules.dup_fuzzy import DupFuzzy
from accumo_rules.context import AllocatedPayment, BankObservation, PaymentToBank
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


def load_bank_context(
    db: Session, organisation_id: uuid.UUID, batch_id: uuid.UUID
) -> tuple[list[PaymentToBank], list[BankObservation]]:
    stmt = (
        select(
            Payment.id,
            Payment.vendor_id,
            VendorIdentity.id,
            VendorIdentity.canonical_name,
            Payment.account_norm,
            Payment.payment_date,
            Payment.amount,
            Payment.currency,
        )
        .join(VendorIdentityMember, VendorIdentityMember.vendor_id == Payment.vendor_id)
        .join(VendorIdentity, VendorIdentity.id == VendorIdentityMember.identity_id)
        .where(
            Payment.organisation_id == organisation_id,
            Payment.batch_id == batch_id,
            Payment.account_norm.is_not(None),
            Payment.vendor_id.is_not(None),
        )
    )
    pays = [
        PaymentToBank(
            payment_id=r[0],
            vendor_id=r[1],
            vendor_identity_id=r[2],
            vendor_name=r[3],
            account_norm=r[4],
            payment_date=r[5],
            amount=r[6],
            currency=r[7],
        )
        for r in db.execute(stmt)
    ]
    vendor_ids = {p.vendor_id for p in pays}
    obs: list[BankObservation] = []
    if vendor_ids:
        banks = db.scalars(select(VendorBankAccount).where(VendorBankAccount.vendor_id.in_(vendor_ids))).all()
        ident_by_vendor = {p.vendor_id: (p.vendor_identity_id, p.vendor_name) for p in pays}
        for b in banks:
            ident, name = ident_by_vendor.get(b.vendor_id, (None, ""))
            if ident is None:
                continue
            obs.append(
                BankObservation(
                    vendor_id=b.vendor_id,
                    vendor_identity_id=ident,
                    vendor_name=name,
                    account_norm=b.account_norm,
                    observed_from=b.observed_from.date(),
                    bank_id=b.id,
                )
            )
    return pays, obs


def run_dup_exact(db: Session, organisation_id: uuid.UUID, batch_id: uuid.UUID):
    """Kept name so /runs stays stable. Runs the money rules we have."""
    return run_money_rules(db, organisation_id, batch_id)


def run_money_rules(
    db: Session,
    organisation_id: uuid.UUID,
    batch_id: uuid.UUID,
    extra: dict | None = None,
):
    payments = load_allocated(db, organisation_id, batch_id)
    bank_pays, observations = load_bank_context(db, organisation_id, batch_id)
    bank_findings = list(BankChangePay().run(bank_pays, observations))
    by_rule = {
        DupExact.code: list(DupExact().run(payments)),
        DupFuzzy.code: list(DupFuzzy().run(payments)),
        BankChangePay.code: bank_findings,
    }
    if extra:
        by_rule.update(extra)
    run = persist_findings(
        db,
        organisation_id=organisation_id,
        batch_id=batch_id,
        by_rule=by_rule,
    )
    run.stats = {
        **(run.stats or {}),
        "bank_change_assessable": is_assessable(observations, bank_pays),
    }
    return run
