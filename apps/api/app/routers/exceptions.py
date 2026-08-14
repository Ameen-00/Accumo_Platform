from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser
from accumo_canonical.models import Exception as ExceptionRow
from accumo_canonical.models import ExceptionEvent
from accumo_foundation.audit import write
from accumo_foundation.auth import current_user, require_roles
from accumo_foundation.disposition import TransitionError, assert_transition

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


class TransitionIn(BaseModel):
    to_status: str
    reason: str | None = None
    recovered_amount: Decimal | None = None
    note: str | None = None


class BulkIn(TransitionIn):
    ids: list[uuid.UUID]


def _owned(db: Session, exc_id: uuid.UUID, user: AppUser) -> ExceptionRow:
    row = db.get(ExceptionRow, exc_id)
    if not row or row.organisation_id != user.organisation_id:
        raise HTTPException(status_code=404, detail="Exception not found")
    return row


def _apply(
    db: Session,
    row: ExceptionRow,
    body: TransitionIn,
    user: AppUser,
    ip: str | None,
) -> ExceptionRow:
    try:
        assert_transition(row.status, body.to_status, body.reason, body.recovered_amount)
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    event = ExceptionEvent(
        exception_id=row.id,
        actor_id=user.id,
        from_status=row.status,
        to_status=body.to_status,
        reason=body.reason,
        recovered_amount=body.recovered_amount,
        note=body.note,
    )
    row.status = body.to_status
    db.add(event)
    write(
        db,
        action="exception.transition",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="exception",
        object_id=row.id,
        detail={"from": event.from_status, "to": event.to_status},
        ip=ip,
    )
    return row


def _money(rows: list[ExceptionRow], status: str | None = None) -> Decimal:
    picked = rows if status is None else [r for r in rows if r.status == status]
    return sum((r.amount_at_risk for r in picked), start=Decimal("0"))


@router.get("")
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
    rows = list(db.scalars(stmt))
    all_rows = (
        rows
        if not status and not rule
        else list(
            db.scalars(select(ExceptionRow).where(ExceptionRow.organisation_id == user.organisation_id))
        )
    )
    recovered = Decimal("0")
    if all_rows:
        recovered = sum(
            (
                e.recovered_amount or Decimal("0")
                for e in db.scalars(
                    select(ExceptionEvent).where(
                        ExceptionEvent.to_status == "recovered",
                        ExceptionEvent.exception_id.in_([r.id for r in all_rows]),
                    )
                )
            ),
            start=Decimal("0"),
        )
    return {
        "identified": str(_money(all_rows)),
        "confirmed": str(_money(all_rows, "confirmed") + _money(all_rows, "recovered")),
        "recovered": str(recovered),
        "count": len(rows),
        "exceptions": [_summary(r) for r in rows],
    }


@router.get("/{exc_id}")
def get_exception(
    exc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    row = _owned(db, exc_id, user)
    events = list(
        db.scalars(
            select(ExceptionEvent)
            .where(ExceptionEvent.exception_id == row.id)
            .order_by(ExceptionEvent.created_at)
        )
    )
    return {
        **_summary(row),
        "explanation": row.explanation,
        "evidence": row.evidence,
        "events": [
            {
                "from": e.from_status,
                "to": e.to_status,
                "reason": e.reason,
                "recovered_amount": str(e.recovered_amount) if e.recovered_amount is not None else None,
                "note": e.note,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.post("/{exc_id}/transition")
def transition(
    exc_id: uuid.UUID,
    body: TransitionIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    row = _owned(db, exc_id, user)
    _apply(db, row, body, user, request.client.host if request.client else None)
    db.commit()
    return _summary(row)


@router.post("/bulk-transition")
def bulk_transition(
    body: BulkIn,
    request: Request,
    db: Session = Depends(get_db),
    user: AppUser = Depends(require_roles("admin", "reviewer")),
):
    ip = request.client.host if request.client else None
    moved = []
    for exc_id in body.ids:
        row = _owned(db, exc_id, user)
        _apply(db, row, body, user, ip)
        moved.append(str(row.id))
    db.commit()
    return {"ok": True, "moved": moved}


def _summary(row: ExceptionRow) -> dict:
    return {
        "id": str(row.id),
        "rule": row.rule_code,
        "status": row.status,
        "title": row.title,
        "amount_at_risk": str(row.amount_at_risk),
        "currency": row.currency,
        "confidence": str(row.confidence),
        "explanation": row.explanation,
    }
