"""Write findings as exceptions. Same fingerprint keeps the old disposition."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.models import Exception as ExceptionRow
from accumo_canonical.models import Run, RuleVersion
from accumo_rules.engine import Finding
from accumo_rules.fingerprint import fingerprint


def persist_findings(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    batch_id: uuid.UUID,
    rule_code: str,
    findings: list[Finding],
) -> Run:
    version = db.scalar(
        select(RuleVersion).where(RuleVersion.rule_code == rule_code, RuleVersion.active.is_(True))
    )
    if version is None:
        raise RuntimeError(f"No active version for {rule_code}")

    now = datetime.now(timezone.utc)
    run = Run(
        organisation_id=organisation_id,
        batch_id=batch_id,
        status="running",
        rule_versions={rule_code: str(version.id)},
        started_at=now,
        stats={},
    )
    db.add(run)
    db.flush()

    created = updated = 0
    for finding in findings:
        fp = fingerprint(rule_code, *finding.fingerprint_parts)
        existing = db.scalar(
            select(ExceptionRow).where(
                ExceptionRow.organisation_id == organisation_id,
                ExceptionRow.fingerprint == fp,
            )
        )
        if existing:
            existing.amount_at_risk = finding.amount_at_risk
            existing.explanation = finding.explanation
            existing.evidence = finding.evidence
            existing.run_id = run.id
            updated += 1
            continue
        db.add(
            ExceptionRow(
                organisation_id=organisation_id,
                run_id=run.id,
                rule_code=rule_code,
                rule_version_id=version.id,
                fingerprint=fp,
                status="new",
                amount_at_risk=finding.amount_at_risk,
                currency=finding.currency,
                confidence=finding.confidence,
                vendor_identity_id=_maybe_uuid(finding.evidence.get("vendor_identity_id")),
                title=finding.title,
                explanation=finding.explanation,
                evidence=finding.evidence,
            )
        )
        created += 1

    run.status = "complete"
    run.finished_at = datetime.now(timezone.utc)
    run.stats = {"created": created, "updated": updated, "findings": len(findings)}
    return run


def _maybe_uuid(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    return uuid.UUID(str(raw))
