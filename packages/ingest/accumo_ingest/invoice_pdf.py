"""Read a supplier tax invoice PDF into canonical-shaped fields.

Deterministic first. If the page has no text, the caller may send it to the
brain — this module never invents a GSTIN or an amount.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b")
INV_RE = re.compile(r"(?:#\s*:|invoice\s*(?:no\.?|number|#)\s*:?)\s*([A-Z0-9][A-Z0-9/_-]{2,})", re.I)
DATE_RE = re.compile(r"(?:invoice\s*date|dated)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.I)
TOTAL_RE = re.compile(r"(?:total|balance\s*due|grand\s*total)\s*[:₹rs.]*\s*([\d,]+\.\d{2})", re.I)
PO_RE = re.compile(r"(?:p\.?o\.?\s*#|purchase\s*order)\s*:?\s*([A-Z0-9][A-Z0-9/_-]{2,})", re.I)


@dataclass
class InvoiceExtract:
    source_ref: str
    invoice_number: str
    invoice_date: str
    amount: str
    currency: str
    vendor_name: str
    vendor_tax_id: str
    buyer_tax_id: str
    po_ref: str
    raw_text: str
    confidence: str
    needs_human: bool
    missing: list[str]


def _money(raw: str) -> str:
    try:
        return str(Decimal(raw.replace(",", "")))
    except (InvalidOperation, AttributeError):
        return ""


def extract_text(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("invoice PDFs need pdfplumber") from exc
    with pdfplumber.open(BytesIO(data)) as doc:
        return "\n".join((p.extract_text() or "") for p in doc.pages)


def parse_invoice_text(text: str, filename: str = "") -> InvoiceExtract:
    gstins = GSTIN_RE.findall(text)
    vendor_gstin = gstins[0] if gstins else ""
    buyer_gstin = gstins[1] if len(gstins) > 1 else ""
    inv = INV_RE.search(text)
    number = inv.group(1).strip() if inv else ""
    if not number and filename.upper().startswith("INV"):
        number = filename.rsplit(".", 1)[0]
    dated = DATE_RE.search(text)
    totals = TOTAL_RE.findall(text)
    amount = _money(totals[-1]) if totals else ""
    po = PO_RE.search(text)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    missing = [n for n, v in (("invoice_number", number), ("amount", amount), ("vendor_name", first)) if not v]
    needs = bool(missing) or not vendor_gstin
    return InvoiceExtract(
        source_ref=number or filename,
        invoice_number=number,
        invoice_date=dated.group(1) if dated else "",
        amount=amount,
        currency="INR",
        vendor_name=first[:120],
        vendor_tax_id=vendor_gstin,
        buyer_tax_id=buyer_gstin,
        po_ref=po.group(1) if po else "",
        raw_text=text[:4000],
        confidence="0.70" if not needs else "0.40",
        needs_human=needs,
        missing=missing,
    )


def parse_invoice_pdf(data: bytes, filename: str) -> InvoiceExtract:
    text = extract_text(data)
    if not text.strip():
        return InvoiceExtract(
            source_ref=filename,
            invoice_number="",
            invoice_date="",
            amount="",
            currency="INR",
            vendor_name="",
            vendor_tax_id="",
            buyer_tax_id="",
            po_ref="",
            raw_text="",
            confidence="0.00",
            needs_human=True,
            missing=["scanned_or_empty"],
        )
    return parse_invoice_text(text, filename)
