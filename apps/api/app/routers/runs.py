from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser, ImportBatch, Run
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
