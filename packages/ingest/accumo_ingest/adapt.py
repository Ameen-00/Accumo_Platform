"""Turn a mixed drop (zip / PDFs / xls) into an environment profile + rows.

The brain classifies and extracts. A human still has to commit.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from accumo_canonical.normalise import normalise_invoice
from accumo_ingest.bank_statement import BankLine, parse_bank_bytes
from accumo_ingest.classify import Environment, FileKind, classify_name, profile
from accumo_ingest.gstr2b import TwoBRow, parse_2b_bytes
from accumo_ingest.invoice_pdf import InvoiceExtract, parse_invoice_pdf
from accumo_ingest.zoho_ledger import LedgerLine, parse_zoho_ledger


@dataclass
class Extracted:
    env: Environment
    invoices: list[InvoiceExtract] = field(default_factory=list)
    bank: list[BankLine] = field(default_factory=list)
    two_b: list[TwoBRow] = field(default_factory=list)
    ledger: list[LedgerLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def expand(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    if not filename.lower().endswith(".zip"):
        return [(filename, data)]
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            name = info.filename.rsplit("/", 1)[-1]
            if not name or name.startswith("."):
                continue
            out.append((name, zf.read(info)))
    return out


def ingest_files(files: list[tuple[str, bytes]]) -> Extracted:
    exploded: list[tuple[str, bytes]] = []
    for name, data in files:
        exploded.extend(expand(name, data))
    kinds: list[FileKind] = []
    extracted = Extracted(env=Environment(mode="zero_books", summary=""))
    for name, data in exploded:
        kind = classify_name(name)
        kinds.append(kind)
        if kind.skip:
            extracted.skipped.append(name)
            continue
        try:
            if kind.kind == "invoice_pdf":
                inv = parse_invoice_pdf(data, name)
                if inv.invoice_number and inv.amount:
                    extracted.invoices.append(inv)
                else:
                    extracted.skipped.append(name)
            elif kind.kind == "document_pdf":
                extracted.skipped.append(name)
            elif kind.kind == "gstr2b":
                extracted.two_b.extend(parse_2b_bytes(data))
            elif kind.kind == "bank_statement":
                extracted.bank.extend(parse_bank_bytes(data, name))
            elif kind.kind == "books_export" and name.lower().endswith(".pdf"):
                extracted.ledger.extend(parse_zoho_ledger(data))
            else:
                extracted.skipped.append(name)
        except Exception as exc:  # noqa: BLE001 — one bad file must not kill the drop
            extracted.errors.append(f"{name}: {exc}")
    extracted.env = profile(kinds)
    return extracted


def invoices_as_rows(items: list[InvoiceExtract]) -> list[dict[str, str]]:
    rows = []
    for i, inv in enumerate(items, start=1):
        rows.append(
            {
                "invoice_id": inv.source_ref or f"I-{i:05d}",
                "invoice_number": inv.invoice_number or inv.source_ref,
                "invoice_date": inv.invoice_date,
                "invoice_amount": inv.amount,
                "currency": inv.currency or "INR",
                "vendor_name": inv.vendor_name,
                "gstin": inv.vendor_tax_id,
            }
        )
    return rows


def vendors_as_rows(items: list[InvoiceExtract]) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for inv in items:
        key = inv.vendor_tax_id or inv.vendor_name
        if not key or key in seen:
            continue
        seen[key] = {
            "vendor_code": inv.vendor_tax_id or inv.vendor_name[:20],
            "vendor_name": inv.vendor_name,
            "gstin": inv.vendor_tax_id,
        }
    return list(seen.values())


def bank_as_payment_rows(items: list[BankLine]) -> list[dict[str, str]]:
    rows = []
    for i, line in enumerate(items, start=1):
        if line.direction != "out":
            continue
        rows.append(
            {
                "payment_id": line.reference or f"P-{i:05d}",
                "payment_date": line.payment_date,
                "payment_amount": line.amount,
                "vendor_name": line.narration[:80],
                "against_invoice": "",
                "bank_account": "",
            }
        )
    return rows


def ledger_as_invoices(items: list[LedgerLine]) -> list[InvoiceExtract]:
    out: list[InvoiceExtract] = []
    for i, line in enumerate(items, start=1):
        if line.kind != "invoice":
            continue
        number = line.reference or line.voucher or f"L-{i:05d}"
        out.append(
            InvoiceExtract(
                source_ref=line.voucher or number,
                invoice_number=number,
                invoice_date=line.date,
                amount=line.amount,
                currency="INR",
                vendor_name=line.vendor,
                vendor_tax_id="",
                buyer_tax_id="",
                po_ref="",
                raw_text=line.details,
                confidence="0.65" if line.reference else "0.45",
                needs_human=not bool(line.reference),
                missing=[] if line.reference else ["invoice_number"],
            )
        )
    return out


def ledger_as_payment_rows(items: list[LedgerLine]) -> list[dict[str, str]]:
    rows = []
    for i, line in enumerate(items, start=1):
        if line.kind != "payment":
            continue
        rows.append(
            {
                "payment_id": line.voucher or f"LP-{i:05d}",
                "payment_date": line.date,
                "payment_amount": line.amount,
                "vendor_name": line.vendor,
                "against_invoice": line.reference,
                "bank_account": "",
            }
        )
    return rows


def merge_invoices(pdfs: list[InvoiceExtract], ledger: list[InvoiceExtract]) -> list[InvoiceExtract]:
    """PDF extract wins when the same invoice number appears in the ledger."""
    have = {normalise_invoice(inv.invoice_number) for inv in pdfs if inv.invoice_number}
    extra = [inv for inv in ledger if normalise_invoice(inv.invoice_number) not in have]
    return list(pdfs) + extra


def reconstructed(extracted: Extracted) -> list[InvoiceExtract]:
    return merge_invoices(extracted.invoices, ledger_as_invoices(extracted.ledger))
