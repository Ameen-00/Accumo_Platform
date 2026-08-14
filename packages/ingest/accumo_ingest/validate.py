"""Validate a mapped file. First 20 errors, with row numbers. Never half-load."""

from __future__ import annotations

from accumo_ingest.mapping import REQUIRED, missing_required
from accumo_ingest.values import date_is_ambiguous, parse_amount, parse_currency, parse_date

DATE_FIELDS = {
    "invoice.invoice_date",
    "payment.payment_date",
    "credit_note.note_date",
    "vendor.created_on",
}
AMOUNT_FIELDS = {
    "invoice.gross_amount",
    "invoice.tax_amount",
    "payment.amount",
    "credit_note.amount",
}


def needs_date_format(rows: list[dict[str, str]], mapping: dict[str, str]) -> bool:
    date_headers = [h for h, f in mapping.items() if f in DATE_FIELDS]
    for row in rows:
        for h in date_headers:
            if date_is_ambiguous(row.get(h)):
                return True
    return False


def validate(
    rows: list[dict[str, str]],
    mapping: dict[str, str],
    entity: str,
    date_format: str | None,
    default_currency: str = "INR",
) -> list[dict]:
    missing = missing_required(mapping, entity)
    errors: list[dict] = []
    if missing:
        errors.append({"row": 0, "field": ",".join(missing), "error": "required fields not mapped"})
        return errors[:20]

    if needs_date_format(rows, mapping) and date_format not in {"dmy", "mdy", "ymd"}:
        errors.append({"row": 0, "field": "date_format", "error": "ambiguous dates — set date_format to dmy or mdy"})
        return errors[:20]

    inverse = {field: header for header, field in mapping.items()}
    for i, row in enumerate(rows, start=2):  # 1 = header
        for field in REQUIRED.get(entity, []):
            header = inverse.get(field)
            if header is None or not str(row.get(header, "")).strip():
                errors.append({"row": i, "field": field, "error": "empty"})
                if len(errors) >= 20:
                    return errors
        for header, field in mapping.items():
            raw = row.get(header, "")
            if raw == "" or raw is None:
                continue
            try:
                if field in DATE_FIELDS:
                    parse_date(raw, date_format)
                elif field in AMOUNT_FIELDS:
                    parse_amount(raw)
                elif field.endswith(".currency"):
                    parse_currency(raw, default_currency)
            except ValueError as exc:
                errors.append({"row": i, "field": field, "error": str(exc)})
                if len(errors) >= 20:
                    return errors
    return errors
