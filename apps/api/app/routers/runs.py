from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser, Exception as ExceptionRow
from accumo_canonical.models import ImportBatch, Run
from accumo_foundation.audit import write
from accumo_foundation.auth import current_user, require_roles
from accumo_pulse.execute import run_dup_exact

router = APIRouter(tags=["runs"])


class RunIn(BaseModel):
    batch_id: uuid.UUID


@router.post("/runs")
def create_run(
    body: RunIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    batch = db.get(ImportBatch, body.batch_id)
    if not batch or batch.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Import not found")
    if batch.status != "loaded":
        raise HTTPException(status_code=409, detail="Import is not loaded yet")
    try:
        run = run_dup_exact(db, batch.organisation_id, batch.id)
        write(
            db,
            action="run.completed",
            actor_id=user.id,
            organisation_id=user.organisation_id,
            object_type="run",
            object_id=run.id,
            detail=run.stats,
            ip=request.client.host if request.client else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id": str(run.id), "status": run.status, "stats": run.stats}


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    run = db.get(Run, run_id)
    if not run or run.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": str(run.id),
        "status": run.status,
        "stats": run.stats,
        "rule_versions": run.rule_versions,
    }


@router.get("/exceptions")
def list_exceptions(
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
    status: str | None = None,
    rule: str | None = None,
):
    stmt = select(ExceptionRow).where(ExceptionRow.organisation_id == user.organisation_id)
    if status:
        stmt = stmt.where(ExceptionRow.status == status)
    if rule:
        stmt = stmt.where(ExceptionRow.rule_code == rule)
    stmt = stmt.order_by(ExceptionRow.amount_at_risk.desc())
    rows = db.scalars(stmt).all()
    identified = sum((r.amount_at_risk for r in rows), start=0)
    return {
        "identified": str(identified),
        "count": len(rows),
        "exceptions": [
            {
                "id": str(r.id),
                "rule": r.rule_code,
                "status": r.status,
                "title": r.title,
                "amount_at_risk": str(r.amount_at_risk),
                "currency": r.currency,
                "confidence": str(r.confidence),
                "explanation": r.explanation,
            }
            for r in rows
        ],
    }
