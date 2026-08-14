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
