from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class AllocatedPayment:
    payment_id: UUID
    invoice_id: UUID
    invoice_norm: str
    invoice_number: str
    amount: Decimal
    currency: str
    payment_date: date
    vendor_identity_id: UUID
    vendor_name: str


@dataclass(frozen=True)
class BankObservation:
    vendor_id: UUID
    vendor_identity_id: UUID
    vendor_name: str
    account_norm: str
    observed_from: date
    bank_id: UUID | None = None


@dataclass(frozen=True)
class PaymentToBank:
    payment_id: UUID
    vendor_id: UUID
    vendor_identity_id: UUID
    vendor_name: str
    account_norm: str
    payment_date: date
    amount: Decimal
    currency: str
