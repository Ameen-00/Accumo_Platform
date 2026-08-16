"""Evidence pack export. Spec §11 / API §12.

POST writes a Job and a ZIP under report_dir. The file is tenant-local.
Audit logs ids and hashes, never the findings themselves.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import (
    AppUser,
    ImportBatch,
    Job,
    Organisation,
    Rule,
    RuleVersion,
    Run,
    SourceFile,
)
from accumo_canonical.models import Exception as ExceptionRow
from accumo_canonical.models import ExceptionEvent
from accumo_foundation.audit import write
from accumo_foundation.auth import current_user, require_roles
from accumo_foundation.config import get_settings
from accumo_pulse.pack import (
    DispositionView,
    ExceptionView,
    PackInput,
    RuleApplied,
    SourceFileInfo,
    build_pack,
    filename_for,
    render_zip,
)

router = APIRouter(prefix="/reports", tags=["reports"])


class PackIn(BaseModel):
    run_id: uuid.UUID


def _actor_name(db: Session, user_id: uuid.UUID | None) -> str:
    if not user_id:
        return "unknown"
    user = db.get(AppUser, user_id)
    if not user:
        return "unknown"
    return user.full_name or user.email


def gather(db: Session, run: Run, generated_by: str) -> PackInput:
    org = db.get(Organisation, run.organisation_id)
    batch = db.get(ImportBatch, run.batch_id)
    if not org or not batch:
        raise HTTPException(status_code=404, detail="Run is missing organisation or import")
    files = [
        SourceFileInfo(
            entity=f.entity,
            filename=f.filename,
            sha256=f.sha256,
            row_count=f.row_count,
        )
        for f in db.scalars(select(SourceFile).where(SourceFile.batch_id == batch.id))
    ]
    rules: list[RuleApplied] = []
    for code, version_id in (run.rule_versions or {}).items():
        version = db.get(RuleVersion, uuid.UUID(str(version_id)))
        rule = db.get(Rule, code)
        if not version:
            continue
        rules.append(
            RuleApplied(
                code=code,
                name=rule.name if rule else code,
                version=version.version,
                params=version.params or {},
            )
        )
    exceptions = list(
        db.scalars(select(ExceptionRow).where(ExceptionRow.run_id == run.id))
    )
    events: list[DispositionView] = []
    if exceptions:
        raw_events = list(
            db.scalars(
                select(ExceptionEvent)
                .where(ExceptionEvent.exception_id.in_([row.id for row in exceptions]))
                .order_by(ExceptionEvent.created_at)
            )
        )
        by_id = {row.id: row for row in exceptions}
        for event in raw_events:
            row = by_id[event.exception_id]
            events.append(
                DispositionView(
                    exception_id=row.id,
                    rule_code=row.rule_code,
                    title=row.title,
                    actor=_actor_name(db, event.actor_id),
                    from_status=event.from_status,
                    to_status=event.to_status,
                    reason=event.reason,
                    recovered_amount=event.recovered_amount,
                    at=event.created_at,
                )
            )
    stats = run.stats or {}
    return PackInput(
        organisation_name=org.name,
        country_code=org.country_code,
        currency=org.base_currency,
        period_start=batch.period_start,
        period_end=batch.period_end,
        run_id=run.id,
        generated_at=datetime.now(timezone.utc),
        generated_by=generated_by,
        files=files,
        row_counts=batch.row_counts or {},
        rules=rules,
        exceptions=[
            ExceptionView(
                id=row.id,
                rule_code=row.rule_code,
                status=row.status,
                title=row.title,
                amount=row.amount_at_risk,
                currency=row.currency,
                confidence=row.confidence,
                explanation=row.explanation or {},
                evidence=row.evidence or {},
            )
            for row in exceptions
        ],
        events=events,
        bank_change_assessable=bool(stats.get("bank_change_assessable")),
        has_change_log=False,
        stats=stats,
    )


def _owned_run(db: Session, run_id: uuid.UUID, user: AppUser) -> Run:
    run = db.get(Run, run_id)
    if not run or run.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _owned_job(db: Session, job_id: uuid.UUID, user: AppUser) -> Job:
    job = db.get(Job, job_id)
    if not job or job.kind != "evidence_pack":
        raise HTTPException(status_code=404, detail="Report not found")
    org = (job.payload or {}).get("organisation_id")
    if org != str(user.organisation_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return job


@router.post("/evidence-pack")
def create_evidence_pack(
    body: PackIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    run = _owned_run(db, body.run_id, user)
    pack = build_pack(gather(db, run, user.full_name or user.email))
    blob = render_zip(pack)
    name = filename_for(pack)
    digest = hashlib.sha256(blob).hexdigest()

    job = Job(
        kind="evidence_pack",
        payload={
            "run_id": str(run.id),
            "organisation_id": str(user.organisation_id),
            "filename": name,
            "sha256": digest,
            "bytes": len(blob),
        },
        status="done",
    )
    db.add(job)
    try:
        db.flush()
        dest = Path(get_settings().report_dir) / f"{job.id}.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        write(
            db,
            action="report.evidence_pack",
            actor_id=user.id,
            organisation_id=user.organisation_id,
            object_type="job",
            object_id=job.id,
            detail={"run_id": str(run.id), "sha256": digest, "findings": len(pack.findings)},
            ip=request.client.host if request.client else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id": str(job.id), "status": job.status, "filename": name, "sha256": digest}


@router.get("/{report_id}")
def get_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    job = _owned_job(db, report_id, user)
    payload = job.payload or {}
    return {
        "id": str(job.id),
        "status": job.status,
        "filename": payload.get("filename"),
        "sha256": payload.get("sha256"),
        "run_id": payload.get("run_id"),
    }


@router.get("/{report_id}/download")
def download_report(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    job = _owned_job(db, report_id, user)
    path = Path(get_settings().report_dir) / f"{job.id}.zip"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report file is gone")
    name = (job.payload or {}).get("filename") or f"pulse-evidence-{job.id}.zip"
    return FileResponse(path, filename=name, media_type="application/zip")
