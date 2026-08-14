"""Commit a validated file into the canonical tables. One transaction, or nothing."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from accumo_canonical.models import CreditNote, Invoice, Payment, PaymentAllocation, Vendor
from accumo_canonical.normalise import normalise_invoice, normalise_name, normalise_tax_id
from accumo_foundation.crypto import account_hmac, encrypt_account
from accumo_ingest.values import parse_amount, parse_currency, parse_date


def _mapped(row: dict[str, str], mapping: dict[str, str], field: str) -> str:
    for header, f in mapping.items():
        if f == field:
            return (row.get(header) or "").strip()
    return ""


def _vendors_in_batch(db: Session, batch_id: uuid.UUID) -> dict[str, Vendor]:
    found: dict[str, Vendor] = {}
    for v in db.query(Vendor).filter(Vendor.batch_id == batch_id):
        found[v.source_ref] = v
        found[v.name_normalised] = v
    return found


def load_rows(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    batch_id: uuid.UUID,
    entity: str,
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    date_format: str | None,
    default_currency: str,
    country_code: str,
) -> int:
    vendors = _vendors_in_batch(db, batch_id)
    invoices: dict[str, Invoice] = {}
    for inv in db.query(Invoice).filter(Invoice.batch_id == batch_id):
        invoices[inv.source_ref] = inv
        invoices[inv.invoice_number] = inv
    n = 0
    for i, row in enumerate(rows, start=1):
        if entity == "vendor":
            _load_vendor(db, organisation_id, batch_id, row, mapping, country_code, i, vendors)
        elif entity == "invoice":
            _load_invoice(db, organisation_id, batch_id, row, mapping, date_format, default_currency, country_code, i, vendors, invoices)
        elif entity == "payment":
            _load_payment(db, organisation_id, batch_id, row, mapping, date_format, default_currency, country_code, i, vendors, invoices)
        elif entity == "credit_note":
            _load_credit(db, organisation_id, batch_id, row, mapping, date_format, default_currency, country_code, i, vendors, invoices)
        else:
            raise ValueError(f"unknown entity {entity}")
        n += 1
    return n


def _load_vendor(db, org, batch, row, mapping, country, i, lookup):
    name = _mapped(row, mapping, "vendor.name")
    source_ref = _mapped(row, mapping, "vendor.source_ref") or f"V-{i:05d}"
    tax = normalise_tax_id(_mapped(row, mapping, "vendor.tax_id") or None)
    v = Vendor(
        organisation_id=org,
        batch_id=batch,
        source_ref=source_ref,
        name=name,
        name_normalised=normalise_name(name),
        tax_id=tax or None,
        registration_id=_mapped(row, mapping, "vendor.registration_id") or None,
        country_code=(_mapped(row, mapping, "vendor.country_code") or country)[:2],
        raw=row,
    )
    db.add(v)
    db.flush()
    lookup[source_ref] = v
    lookup[v.name_normalised] = v


def _vendor_of(db, org, batch, row, mapping, country, lookup) -> Vendor | None:
    ref = _mapped(row, mapping, "vendor.source_ref")
    if ref and ref in lookup:
        return lookup[ref]
    raw_name = _mapped(row, mapping, "vendor.name")
    name = normalise_name(raw_name)
    if name and name in lookup:
        return lookup[name]
    if not raw_name and not ref:
        return None
    source_ref = ref or f"V-auto-{len(lookup)+1:05d}"
    v = Vendor(
        organisation_id=org,
        batch_id=batch,
        source_ref=source_ref,
        name=raw_name or source_ref,
        name_normalised=name or source_ref,
        tax_id=normalise_tax_id(_mapped(row, mapping, "vendor.tax_id") or None) or None,
        country_code=country,
        raw=row,
    )
    db.add(v)
    db.flush()
    lookup[v.source_ref] = v
    lookup[v.name_normalised] = v
    return v


def _load_invoice(db, org, batch, row, mapping, date_format, currency, country, i, vendors, invoices):
    number = _mapped(row, mapping, "invoice.invoice_number")
    amount = parse_amount(_mapped(row, mapping, "invoice.gross_amount")) or Decimal("0")
    day = parse_date(_mapped(row, mapping, "invoice.invoice_date") or None, date_format)
    vendor = _vendor_of(db, org, batch, row, mapping, country, vendors)
    inv = Invoice(
        organisation_id=org,
        batch_id=batch,
        source_ref=_mapped(row, mapping, "invoice.source_ref") or f"I-{i:07d}",
        vendor_id=vendor.id if vendor else None,
        invoice_number=number,
        invoice_norm=normalise_invoice(number),
        invoice_date=day,
        gross_amount=amount,
        tax_amount=parse_amount(_mapped(row, mapping, "invoice.tax_amount") or None),
        currency=parse_currency(_mapped(row, mapping, "invoice.currency") or None, currency),
        raw=row,
    )
    db.add(inv)
    invoices[inv.source_ref] = inv
    invoices[number] = inv


def _load_payment(db, org, batch, row, mapping, date_format, currency, country, i, vendors, invoices):
    amount = parse_amount(_mapped(row, mapping, "payment.amount")) or Decimal("0")
    day = parse_date(_mapped(row, mapping, "payment.payment_date"), date_format)
    if day is None:
        raise ValueError("payment_date required")
    vendor = _vendor_of(db, org, batch, row, mapping, country, vendors)
    bank = _mapped(row, mapping, "payment.account")
    pay = Payment(
        organisation_id=org,
        batch_id=batch,
        source_ref=_mapped(row, mapping, "payment.source_ref") or f"P-{i:07d}",
        vendor_id=vendor.id if vendor else None,
        payment_date=day,
        amount=amount,
        currency=parse_currency(_mapped(row, mapping, "payment.currency") or None, currency),
        method=_mapped(row, mapping, "payment.method") or None,
        reference=_mapped(row, mapping, "payment.reference") or None,
        bank_account_to=encrypt_account(bank) if bank else None,
        account_norm=account_hmac(bank) if bank else None,
        raw=row,
    )
    db.add(pay)
    db.flush()
    inv_ref = _mapped(row, mapping, "payment.invoice_ref")
    inv = invoices.get(inv_ref) if inv_ref else None
    if inv is not None:
        db.add(PaymentAllocation(payment_id=pay.id, invoice_id=inv.id, amount=amount))


def _load_credit(db, org, batch, row, mapping, date_format, currency, country, i, vendors, invoices):
    amount = parse_amount(_mapped(row, mapping, "credit_note.amount")) or Decimal("0")
    vendor = _vendor_of(db, org, batch, row, mapping, country, vendors)
    inv_ref = _mapped(row, mapping, "credit_note.invoice_ref")
    inv = invoices.get(inv_ref) if inv_ref else None
    db.add(
        CreditNote(
            organisation_id=org,
            batch_id=batch,
            source_ref=_mapped(row, mapping, "credit_note.source_ref") or f"CN-{i:05d}",
            vendor_id=vendor.id if vendor else None,
            invoice_id=inv.id if inv is not None else None,
            note_date=parse_date(_mapped(row, mapping, "credit_note.note_date") or None, date_format),
            amount=amount,
            currency=parse_currency(None, currency),
            applied=False,
            raw=row,
        )
    )
