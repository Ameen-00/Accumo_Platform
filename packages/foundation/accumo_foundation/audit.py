"""Append-only audit. Log ids and counts — never customer payloads."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from accumo_canonical.models import AuditLog
from accumo_foundation.config import get_settings

log = logging.getLogger("accumo")


def write(
    db: Session,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    organisation_id: uuid.UUID | None = None,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    if get_settings().log_customer_payloads:
        raise RuntimeError("LOG_CUSTOMER_PAYLOADS must stay false")
    db.add(
        AuditLog(
            action=action,
            actor_id=actor_id,
            organisation_id=organisation_id,
            object_type=object_type,
            object_id=object_id,
            detail=detail,
            ip=ip,
        )
    )
    log.info("audit action=%s object_type=%s object_id=%s", action, object_type, object_id)
