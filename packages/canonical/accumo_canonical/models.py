"""Canonical model — jurisdiction-neutral. Money is Numeric(18,4). Never float."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from accumo_canonical.db import Base

Money = Numeric(18, 4)
Conf = Numeric(4, 3)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Organisation(Base):
    __tablename__ = "organisation"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"))
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # admin|reviewer|viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    row_counts: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceFile(Base):
    __tablename__ = "source_file"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    column_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)


class Vendor(Base):
    __tablename__ = "vendor"
    __table_args__ = (
        UniqueConstraint("organisation_id", "batch_id", "source_ref"),
        Index("ix_vendor_org_name_norm", "organisation_id", "name_normalised"),
        Index("ix_vendor_org_tax", "organisation_id", "tax_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(Text)
    registration_id: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    created_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class VendorIdentity(Base):
    __tablename__ = "vendor_identity"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Conf, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VendorIdentityMember(Base):
    __tablename__ = "vendor_identity_member"

    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_identity.id"), primary_key=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor.id"), primary_key=True)


class VendorBankAccount(Base):
    __tablename__ = "vendor_bank_account"
    __table_args__ = (Index("ix_vba_account_norm", "account_norm"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor.id"), nullable=False)
    account_number: Mapped[str] = mapped_column(Text, nullable=False)  # ciphertext
    account_norm: Mapped[str] = mapped_column(Text, nullable=False)  # HMAC
    ifsc_swift: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    account_holder: Mapped[str | None] = mapped_column(Text)
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_source: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)


class PurchaseOrder(Base):
    __tablename__ = "purchase_order"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor.id"))
    po_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class GoodsReceipt(Base):
    __tablename__ = "goods_receipt"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_order.id"))
    receipt_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal | None] = mapped_column(Money)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Invoice(Base):
    __tablename__ = "invoice"
    __table_args__ = (
        Index("ix_invoice_org_norm", "organisation_id", "invoice_norm"),
        Index("ix_invoice_org_vendor_amt", "organisation_id", "vendor_id", "gross_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor.id"))
    invoice_number: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_norm: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_order.id"))
    gross_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    net_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Payment(Base):
    __tablename__ = "payment"
    __table_args__ = (
        Index("ix_payment_org_vendor_date", "organisation_id", "vendor_id", "payment_date"),
        Index("ix_payment_org_amount", "organisation_id", "amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor.id"))
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    method: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    bank_account_to: Mapped[str | None] = mapped_column(Text)  # ciphertext if stored
    account_norm: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(Text)
    posted_by: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PaymentAllocation(Base):
    __tablename__ = "payment_allocation"

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payment.id"), primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice.id"), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)


class CreditNote(Base):
    __tablename__ = "credit_note"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor.id"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice.id"))
    note_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)


class EmployeeBankAccount(Base):
    __tablename__ = "employee_bank_account"
    __table_args__ = (Index("ix_eba_org_norm", "organisation_id", "account_norm"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    employee_ref: Mapped[str] = mapped_column(Text, nullable=False)
    account_norm: Mapped[str] = mapped_column(Text, nullable=False)
    ifsc_swift: Mapped[str | None] = mapped_column(Text)


class Rule(Base):
    __tablename__ = "rule"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)


class RuleVersion(Base):
    __tablename__ = "rule_version"
    __table_args__ = (UniqueConstraint("rule_code", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    rule_code: Mapped[str] = mapped_column(Text, ForeignKey("rule.code"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    __tablename__ = "run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batch.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    rule_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict | None] = mapped_column(JSONB)


class Exception(Base):
    __tablename__ = "exception"
    __table_args__ = (
        UniqueConstraint("organisation_id", "fingerprint"),
        Index("ix_exception_org_status_amt", "organisation_id", "status", "amount_at_risk"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisation.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    rule_code: Mapped[str] = mapped_column(Text, ForeignKey("rule.code"), nullable=False)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rule_version.id"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")
    amount_at_risk: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Conf, nullable=False)
    vendor_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vendor_identity.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExceptionEvent(Base):
    __tablename__ = "exception_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    exception_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exception.id"), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    recovered_amount: Mapped[Decimal | None] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (Index("ix_job_status_run_after", "status", "run_after"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Silence unused import warning for relationship if unused
_ = relationship
