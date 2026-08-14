"""Column mapping. Aliases are jurisdiction-neutral. Templates live per org."""

from __future__ import annotations

from rapidfuzz import fuzz

ALIASES: dict[str, list[str]] = {
    "vendor.name": ["vendor", "vendor_name", "supplier", "supplier_name", "party", "ledger", "particulars"],
    "vendor.source_ref": ["vend_no", "vendor_code", "vendor_id", "supplier_id", "party_code"],
    "vendor.tax_id": ["gstin", "trn", "vat", "tax_id", "gst_no", "vat_no"],
    "vendor.registration_id": ["pan", "cr", "cr_number", "registration"],
    "vendor.country_code": ["country", "country_code"],
    "invoice.invoice_number": ["invoice", "invoice_no", "invoice_number", "bill_no", "bill", "inv"],
    "invoice.invoice_date": ["invoice_date", "bill_date", "inv_date"],
    "invoice.gross_amount": ["gross", "invoice_amount", "gross_amount", "taxable"],
    "invoice.tax_amount": ["tax", "tax_amount", "gst_amount", "vat_amount"],
    "invoice.currency": ["currency", "ccy"],
    "invoice.source_ref": ["invoice_id", "inv_ref"],
    "payment.amount": ["paid", "payment_amount", "debit", "credit"],
    "payment.payment_date": ["payment_date", "txn_date", "paid_on", "value_date"],
    "payment.account": ["bank", "bank_account", "account_no", "iban", "account"],
    "payment.reference": ["utr", "cheque", "payment_ref", "ref", "voucher"],
    "payment.method": ["method", "mode", "pay_mode"],
    "payment.source_ref": ["payment_id", "vch_no"],
    "payment.invoice_ref": ["against_invoice", "bill_ref"],
    "credit_note.amount": ["credit_amount", "cn_amount"],
    "credit_note.note_date": ["cn_date", "credit_date", "note_date"],
    "credit_note.source_ref": ["cn_no", "credit_note", "cn_ref"],
    "credit_note.invoice_ref": ["original_invoice", "against"],
}

# Generic "date" / "amount" only win if nothing more specific matched.
_WEAK = {
    "date": ["invoice.invoice_date", "payment.payment_date", "credit_note.note_date"],
    "amount": ["invoice.gross_amount", "payment.amount", "credit_note.amount"],
}

ENTITIES = ("vendor", "invoice", "payment", "credit_note")

REQUIRED: dict[str, list[str]] = {
    "vendor": ["vendor.name"],
    "invoice": ["invoice.invoice_number", "invoice.gross_amount"],
    "payment": ["payment.amount", "payment.payment_date"],
    "credit_note": ["credit_note.amount"],
}


def _norm(header: str) -> str:
    return header.lower().strip().replace(" ", "_").replace("-", "_")


def suggest(header: str, entity: str | None = None) -> str | None:
    h = _norm(header)
    # Exact alias
    for field, names in ALIASES.items():
        if entity and not field.startswith(entity + ".") and field.split(".")[0] != "vendor":
            # vendor fields are allowed on every entity (to join)
            if not field.startswith("vendor."):
                continue
        if h in names or h == field.split(".")[-1]:
            return field
    if h in _WEAK:
        options = _WEAK[h]
        if entity:
            for opt in options:
                if opt.startswith(entity + "."):
                    return opt
        return options[0]
    # Fuzzy against aliases
    best, score = None, 0
    for field, names in ALIASES.items():
        for name in names + [field.split(".")[-1]]:
            s = fuzz.ratio(h, name)
            if s > score:
                best, score = field, s
    return best if score >= 88 else None


def suggest_all(headers: list[str], entity: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for header in headers:
        if not header:
            continue
        field = suggest(header, entity)
        if field and field not in used:
            mapping[header] = field
            used.add(field)
    return mapping


def missing_required(mapping: dict[str, str], entity: str) -> list[str]:
    have = set(mapping.values())
    return [f for f in REQUIRED[entity] if f not in have]
