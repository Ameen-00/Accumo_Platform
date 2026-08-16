"""Adaptive drop. Mixed files in, a human-reviewed reconstruction out."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser, ImportBatch, SourceFile
from accumo_canonical.resolve import resolve_new_vendors
from accumo_foundation.audit import write
from accumo_foundation.auth import require_roles
from accumo_foundation.config import get_settings
from accumo_ingest.adapt import (
    bank_as_payment_rows,
    ingest_files,
    invoices_as_rows,
    ledger_as_payment_rows,
    reconstructed,
    vendors_as_rows,
)
from accumo_ingest.load import load_rows
from accumo_pulse.execute import run_money_rules
from accumo_ingest.values import parse_date
from accumo_rules.desk import build_desk

router = APIRouter(prefix="/intake", tags=["intake"])

VENDOR_MAP = {"vendor_code": "vendor.source_ref", "vendor_name": "vendor.name", "gstin": "vendor.tax_id"}
INVOICE_MAP = {
    "invoice_id": "invoice.source_ref",
    "invoice_number": "invoice.invoice_number",
    "invoice_date": "invoice.invoice_date",
    "invoice_amount": "invoice.gross_amount",
    "currency": "invoice.currency",
    "vendor_name": "vendor.name",
    "gstin": "vendor.tax_id",
}
PAYMENT_MAP = {
    "payment_id": "payment.source_ref",
    "payment_date": "payment.payment_date",
    "payment_amount": "payment.amount",
    "vendor_name": "vendor.name",
}


def _extract_path(batch_id: uuid.UUID) -> Path:
    dest = Path(get_settings().upload_dir) / str(batch_id)
    dest.mkdir(parents=True, exist_ok=True)
    return dest / "extract.json"


def _dump_extract(batch_id: uuid.UUID, extracted) -> None:
    invoices = reconstructed(extracted)
    payments = bank_as_payment_rows(extracted.bank) + ledger_as_payment_rows(extracted.ledger)
    payload = {
        "mode": extracted.env.mode,
        "summary": extracted.env.summary,
        "limitations": extracted.env.limitations,
        "counts": extracted.env.counts,
        "files": [{"filename": f.filename, "kind": f.kind, "reason": f.reason, "skip": f.skip} for f in extracted.env.files],
        "invoices": [inv.__dict__ for inv in invoices],
        "bank_out": sum(1 for b in extracted.bank if b.direction == "out"),
        "bank_in": sum(1 for b in extracted.bank if b.direction == "in"),
        "two_b": len(extracted.two_b),
        "ledger": len(extracted.ledger),
        "ledger_invoices": sum(1 for line in extracted.ledger if line.kind == "invoice"),
        "ledger_payments": sum(1 for line in extracted.ledger if line.kind == "payment"),
        "needs_human_invoices": sum(1 for i in invoices if i.needs_human),
        "skipped": extracted.skipped,
        "errors": extracted.errors,
        "vendor_rows": vendors_as_rows(invoices),
        "invoice_rows": invoices_as_rows(invoices),
        "payment_rows": payments,
        "bank_rows": [b.__dict__ for b in extracted.bank],
        "two_b_rows": [r.__dict__ for r in extracted.two_b],
        "ledger_rows": [line.__dict__ for line in extracted.ledger],
    }
    _extract_path(batch_id).write_text(json.dumps(payload, default=str), encoding="utf-8")
    return payload


@router.post("/drop")
async def drop(
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    if not user.organisation_id:
        raise HTTPException(status_code=400, detail="User has no organisation")
    incoming: list[tuple[str, bytes]] = []
    for f in files:
        incoming.append((f.filename or "upload.bin", await f.read()))
    extracted = ingest_files(incoming)
    rebuilt = reconstructed(extracted)
    dates = []
    for inv in rebuilt:
        if not inv.invoice_date:
            continue
        try:
            dates.append(parse_date(inv.invoice_date, "dmy"))
        except ValueError:
            continue
    batch = ImportBatch(
        organisation_id=user.organisation_id,
        source="adaptive",
        status="mapping",
        date_format="dmy",
        created_by=user.id,
        period_start=min(dates) if dates else None,
        period_end=max(dates) if dates else None,
        row_counts={"mode": extracted.env.mode},
    )
    db.add(batch)
    db.flush()
    dest = Path(get_settings().upload_dir) / str(batch.id)
    dest.mkdir(parents=True, exist_ok=True)
    exploded: list[tuple[str, bytes]] = []
    from accumo_ingest.adapt import expand

    for name, data in incoming:
        exploded.extend(expand(name, data))
    for name, data in exploded:
        digest = hashlib.sha256(data).hexdigest()
        stored = dest / f"{uuid.uuid4().hex}_{name}"
        stored.write_bytes(data)
        kind = next((f.kind for f in extracted.env.files if f.filename == name), "unknown")
        db.add(
            SourceFile(
                batch_id=batch.id,
                entity=kind,
                filename=name,
                sha256=digest,
                row_count=None,
                column_mapping={},
                stored_path=str(stored),
            )
        )
    preview = _dump_extract(batch.id, extracted)
    write(
        db,
        action="intake.drop",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="import_batch",
        object_id=batch.id,
        detail={
            "mode": extracted.env.mode,
            "invoices": len(rebuilt),
            "two_b": len(extracted.two_b),
            "ledger": len(extracted.ledger),
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    preview["batch_id"] = str(batch.id)
    for key in ("two_b_rows", "bank_rows", "ledger_rows", "vendor_rows", "invoice_rows", "payment_rows"):
        preview.pop(key, None)
    preview["invoices"] = [
        {
            "invoice_number": i["invoice_number"],
            "amount": i["amount"],
            "vendor_name": i["vendor_name"],
            "needs_human": i["needs_human"],
            "missing": i["missing"],
        }
        for i in preview["invoices"][:20]
    ]
    return preview


@router.post("/{batch_id}/commit-and-run")
def commit_and_run(
    batch_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Intake not found")
    path = _extract_path(batch.id)
    if not path.exists():
        raise HTTPException(status_code=409, detail="Nothing to commit — drop files first")
    payload = json.loads(path.read_text(encoding="utf-8"))
    settings = get_settings()
    org = user.organisation_id
    counts: dict[str, int] = {}
    if payload.get("vendor_rows"):
        counts["vendor"] = load_rows(
            db,
            organisation_id=org,
            batch_id=batch.id,
            entity="vendor",
            rows=payload["vendor_rows"],
            mapping=VENDOR_MAP,
            date_format="dmy",
            default_currency=settings.base_currency,
            country_code=settings.country_code,
        )
    if payload.get("invoice_rows"):
        counts["invoice"] = load_rows(
            db,
            organisation_id=org,
            batch_id=batch.id,
            entity="invoice",
            rows=payload["invoice_rows"],
            mapping=INVOICE_MAP,
            date_format="dmy",
            default_currency=settings.base_currency,
            country_code=settings.country_code,
        )
    if payload.get("payment_rows"):
        counts["payment"] = load_rows(
            db,
            organisation_id=org,
            batch_id=batch.id,
            entity="payment",
            rows=payload["payment_rows"],
            mapping=PAYMENT_MAP,
            date_format="dmy",
            default_currency=settings.base_currency,
            country_code=settings.country_code,
        )
    resolve_new_vendors(db, org)
    batch.status = "loaded"
    batch.row_counts = {**counts, "mode": payload.get("mode"), "identities": "resolved"}
    from accumo_ingest.gstr2b import TwoBRow
    from accumo_ingest.invoice_pdf import InvoiceExtract

    invoices = [
        InvoiceExtract(
            source_ref=raw.get("source_ref") or "",
            invoice_number=raw.get("invoice_number") or "",
            invoice_date=raw.get("invoice_date") or "",
            amount=raw.get("amount") or "",
            currency=raw.get("currency") or "INR",
            vendor_name=raw.get("vendor_name") or "",
            vendor_tax_id=raw.get("vendor_tax_id") or "",
            buyer_tax_id=raw.get("buyer_tax_id") or "",
            po_ref=raw.get("po_ref") or "",
            raw_text=raw.get("raw_text") or "",
            confidence=raw.get("confidence") or "0.40",
            needs_human=bool(raw.get("needs_human")),
            missing=list(raw.get("missing") or []),
        )
        for raw in payload.get("invoices", [])
    ]
    two_b = [TwoBRow(**r) for r in payload.get("two_b_rows") or []]
    from accumo_ingest.bank_statement import BankLine

    bank = [BankLine(**r) for r in payload.get("bank_rows") or []]
    extra = build_desk(invoices, bank, two_b)
    try:
        run = run_money_rules(db, org, batch.id, extra=extra)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=(
                "Pulse could not save the findings for this drop. Nothing was booked. "
                "Press Review findings again."
            ),
        ) from exc
    run.stats = {
        **(run.stats or {}),
        "mode": payload.get("mode"),
        "summary": payload.get("summary"),
        "limitations": payload.get("limitations") or [],
        "invoices": len(invoices),
        "payments": counts.get("payment", 0),
        "two_b": len(two_b),
        "suggested": len(extra.get("MATCH_SUGGEST") or []),
        "dup_docs": len(extra.get("DUP_DOC") or []),
        "dup_revised": len(extra.get("DUP_REVISED") or []),
        "open_invoices": len(extra.get("OPEN_INVOICE") or []),
        "open_bank": int(((extra.get("OPEN_BANK") or [None])[0].evidence or {}).get("count") or 0)
        if extra.get("OPEN_BANK")
        else 0,
        "credits": len(extra.get("CREDIT_UNAPPLIED") or []),
        "two_b_gaps": len(extra.get("COMP_2B_ORPHAN") or []),
        "invoices_on_2b": len(invoices) - len(extra.get("COMP_2B_MISSING") or []),
        "ledger": payload.get("ledger") or 0,
        "ledger_invoices": payload.get("ledger_invoices") or 0,
        "ledger_payments": payload.get("ledger_payments") or 0,
        "bank_files": int((payload.get("counts") or {}).get("bank_statement") or 0)
        + int((payload.get("counts") or {}).get("bank_pdf") or 0),
    }
    from accumo_foundation.brain import brief_run
    from accumo_foundation.guide import briefing as build_briefing

    guide = build_briefing(run.stats)
    guide["voice"] = brief_run(guide)
    run.stats = {**(run.stats or {}), "briefing": guide}
    write(
        db,
        action="intake.committed",
        actor_id=user.id,
        organisation_id=org,
        object_type="import_batch",
        object_id=batch.id,
        detail=counts,
        ip=request.client.host if request.client else None,
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=(
                "Pulse could not save the findings for this drop. Nothing was booked. "
                "Press Review findings again."
            ),
        ) from exc
    return {
        "ok": True,
        "batch_id": str(batch.id),
        "run_id": str(run.id),
        "counts": counts,
        "mode": payload.get("mode"),
        "limitations": payload.get("limitations") or [],
        "stats": run.stats,
    }
