"""Pulse rule catalogue. Atlas will add its own seed; same Rule / RuleVersion tables."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.models import AppUser, Organisation, Rule, RuleVersion
from accumo_foundation.auth import hash_password
from accumo_foundation.config import get_settings
from accumo_pulse.catalogue import RULES


def seed_rules(db: Session) -> None:
    for code, name, desc, cat, params in RULES:
        if not db.get(Rule, code):
            db.add(Rule(code=code, name=name, description=desc, category=cat))
        exists = db.scalar(select(RuleVersion).where(RuleVersion.rule_code == code, RuleVersion.version == 1))
        if not exists:
            db.add(RuleVersion(rule_code=code, version=1, params=params, active=True))


def seed_dev_admin(db: Session, email: str = "admin@example.com", password: str = "change-me-now") -> AppUser:
    settings = get_settings()
    org = db.scalar(select(Organisation))
    if not org:
        org = Organisation(name="Dev tenant", country_code=settings.country_code, base_currency=settings.base_currency)
        db.add(org)
        db.flush()
    user = db.scalar(select(AppUser).where(AppUser.email == email))
    if not user:
        user = AppUser(
            organisation_id=org.id,
            email=email,
            password_hash=hash_password(password),
            full_name="Pulse admin",
            role="admin",
        )
        db.add(user)
    return user
