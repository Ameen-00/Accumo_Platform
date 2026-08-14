"""Column mapping — week 2. Aliases are jurisdiction-neutral."""

from __future__ import annotations

ALIASES: dict[str, list[str]] = {
    "vendor.name": ["vendor", "vendor_name", "supplier", "supplier_name", "party", "ledger"],
    "vendor.source_ref": ["vend_no", "vendor_code", "supplier_id"],
    "vendor.tax_id": ["gstin", "trn", "vat", "tax_id", "gst_no"],
    "invoice.invoice_number": ["invoice", "invoice_no", "bill_no", "inv"],
    "invoice.invoice_date": ["date", "invoice_date", "bill_date"],
    "invoice.gross_amount": ["amount", "gross", "invoice_amount"],
    "payment.amount": ["amount", "paid", "debit"],
    "payment.payment_date": ["date", "payment_date", "txn_date"],
    "payment.account": ["bank", "bank_account", "account_no", "iban"],
}


def suggest(header: str) -> str | None:
    h = header.lower().strip().replace(" ", "_")
    for field, names in ALIASES.items():
        if h in names or h == field.split(".")[-1]:
            return field
    return None
