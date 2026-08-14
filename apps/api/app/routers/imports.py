"""CSV / Excel import. Spec §5. File stays on this machine; we log ids and counts only."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser, ImportBatch, MappingTemplate, SourceFile
from accumo_foundation.audit import write
from accumo_foundation.auth import current_user, require_roles
from accumo_foundation.config import get_settings
from accumo_ingest.load import load_rows
from accumo_ingest.mapping import ENTITIES, missing_required, suggest_all
from accumo_ingest.parse import parse_path, parse_upload
from accumo_ingest.validate import needs_date_format, validate

router = APIRouter(prefix="/imports", tags=["imports"])


class MapIn(BaseModel):
    mapping: dict[str, str]
    date_format: str | None = None  # ymd | dmy | mdy


def _batch(db: Session, batch_id: uuid.UUID, user: AppUser) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Import not found")
    return batch


def _headers_key(headers: list[str]) -> str:
    return "|".join(sorted(h.strip() for h in headers if h.strip()))


@router.post("")
def create_import(
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    if not user.organisation_id:
        raise HTTPException(status_code=400, detail="User has no organisation")
    batch = ImportBatch(
        organisation_id=user.organisation_id,
        source="csv",
        status="pending",
        created_by=user.id,
    )
    db.add(batch)
    db.flush()
    write(
        db,
        action="import.created",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="import_batch",
        object_id=batch.id,
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"id": str(batch.id), "status": batch.status}


@router.get("/{batch_id}")
def get_import(
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    batch = _batch(db, batch_id, user)
    files = db.scalars(select(SourceFile).where(SourceFile.batch_id == batch.id)).all()
    return {
        "id": str(batch.id),
        "status": batch.status,
        "date_format": batch.date_format,
        "row_counts": batch.row_counts,
        "files": [
            {
                "id": str(f.id),
                "entity": f.entity,
                "filename": f.filename,
                "row_count": f.row_count,
                "mapping": f.column_mapping,
            }
            for f in files
        ],
    }


@router.post("/{batch_id}/files")
async def upload_file(
    batch_id: uuid.UUID,
    request: Request,
    entity: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    if entity not in ENTITIES:
        raise HTTPException(status_code=400, detail=f"entity must be one of {ENTITIES}")
    batch = _batch(db, batch_id, user)
    if batch.status == "loaded":
        raise HTTPException(status_code=409, detail="This import is already loaded. Start a new one.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    filename = file.filename or "upload.csv"
    try:
        headers, rows = parse_upload(filename, data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not headers:
        raise HTTPException(status_code=400, detail="No header row found")

    digest = hashlib.sha256(data).hexdigest()
    dest_dir = Path(get_settings().upload_dir) / str(batch.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"{uuid.uuid4().hex}_{filename}"
    stored.write_bytes(data)

    suggested = suggest_all(headers, entity)
    template = db.scalar(
        select(MappingTemplate).where(
            MappingTemplate.organisation_id == batch.organisation_id,
            MappingTemplate.entity == entity,
            MappingTemplate.headers_key == _headers_key(headers),
        )
    )
    mapping = template.column_mapping if template else suggested

    src = SourceFile(
        batch_id=batch.id,
        entity=entity,
        filename=filename,
        sha256=digest,
        row_count=len(rows),
        column_mapping=mapping,
        stored_path=str(stored),
    )
    db.add(src)
    batch.status = "mapping"
    write(
        db,
        action="import.file",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="source_file",
        object_id=src.id,
        detail={"entity": entity, "rows": len(rows), "bytes": len(data)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {
        "id": str(src.id),
        "entity": entity,
        "filename": filename,
        "headers": headers,
        "row_count": len(rows),
        "suggested_mapping": suggested,
        "mapping": mapping,
        "from_template": bool(template),
        "preview": rows[:5],
        "needs_date_format": needs_date_format(rows, mapping),
        "missing": missing_required(mapping, entity),
    }


@router.put("/{batch_id}/files/{file_id}/map")
def confirm_map(
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    body: MapIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    batch = _batch(db, batch_id, user)
    src = db.get(SourceFile, file_id)
    if not src or src.batch_id != batch.id:
        raise HTTPException(status_code=404, detail="File not found")
    headers, rows = parse_path(Path(src.stored_path))
    errors = validate(
        rows,
        body.mapping,
        src.entity,
        body.date_format or batch.date_format,
        default_currency=get_settings().base_currency,
    )
    src.column_mapping = body.mapping
    if body.date_format:
        batch.date_format = body.date_format
    if not errors:
        tmpl = db.scalar(
            select(MappingTemplate).where(
                MappingTemplate.organisation_id == batch.organisation_id,
                MappingTemplate.entity == src.entity,
                MappingTemplate.headers_key == _headers_key(headers),
            )
        )
        if tmpl:
            tmpl.column_mapping = body.mapping
        else:
            db.add(
                MappingTemplate(
                    organisation_id=batch.organisation_id,
                    entity=src.entity,
                    headers_key=_headers_key(headers),
                    column_mapping=body.mapping,
                )
            )
    write(
        db,
        action="import.mapped",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="source_file",
        object_id=src.id,
        detail={"error_count": len(errors)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"ok": not errors, "errors": errors, "needs_date_format": needs_date_format(rows, body.mapping)}


@router.post("/{batch_id}/commit")
def commit_import(
    batch_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    batch = _batch(db, batch_id, user)
    files = list(db.scalars(select(SourceFile).where(SourceFile.batch_id == batch.id)))
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    settings = get_settings()
    all_errors: list[dict] = []
    parsed: list[tuple[SourceFile, list[dict[str, str]]]] = []
    for src in files:
        _headers, rows = parse_path(Path(src.stored_path))
        errors = validate(rows, src.column_mapping, src.entity, batch.date_format, settings.base_currency)
        for err in errors:
            err["file"] = src.filename
            all_errors.append(err)
        parsed.append((src, rows))
    if all_errors:
        batch.status = "failed"
        db.commit()
        return {"ok": False, "errors": all_errors[:20]}

    counts: dict[str, int] = {}
    try:
        for src, rows in parsed:
            n = load_rows(
                db,
                organisation_id=batch.organisation_id,
                batch_id=batch.id,
                entity=src.entity,
                rows=rows,
                mapping=src.column_mapping,
                date_format=batch.date_format,
                default_currency=settings.base_currency,
                country_code=settings.country_code,
            )
            counts[src.entity] = counts.get(src.entity, 0) + n
        batch.row_counts = counts
        batch.status = "loaded"
        write(
            db,
            action="import.committed",
            actor_id=user.id,
            organisation_id=user.organisation_id,
            object_type="import_batch",
            object_id=batch.id,
            detail={"counts": counts},
            ip=request.client.host if request.client else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        batch = db.get(ImportBatch, batch_id)
        if batch:
            batch.status = "failed"
            db.commit()
        raise
    return {"ok": True, "counts": counts}
