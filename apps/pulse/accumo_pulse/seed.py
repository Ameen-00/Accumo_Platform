"""Pulse rule catalogue. Atlas will add its own seed; same Rule / RuleVersion tables."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.models import AppUser, Organisation, Rule, RuleVersion
from accumo_foundation.auth import hash_password
from accumo_foundation.config import get_settings

RULES = [
    ("DUP_EXACT", "Exact duplicate payment", "Same vendor, same invoice, same amount, paid more than once.", "recovery", {"window_days": 365}),
    ("DUP_FUZZY", "Probable duplicate", "Same vendor and amount, invoice numbers almost match.", "recovery", {"window_days": 90, "min_similarity": 85}),
    ("DUP_VENDOR", "Duplicate vendor master", "One real supplier living under two vendor codes.", "risk", {}),
    ("BANK_CHANGE_PAY", "Bank detail changed, then paid", "Vendor account changed and a payment followed.", "risk", {"window_days": 30}),
    ("NO_PO", "Payment without PO or receipt", "Paid where process required a PO or GRN.", "risk", {"min_amount": None, "require_grn": True}),
    ("THRESHOLD", "Approval limit circumvention", "Several payments just under a limit, same vendor, short window.", "risk", {"thresholds": [], "window_days": 30, "min_count": 3}),
    ("VENDOR_IS_EMPLOYEE", "Vendor bank matches payroll", "A vendor is paid into an employee account.", "risk", {}),
    ("CREDIT_UNAPPLIED", "Credit note never applied", "Credit issued, still open, vendor still being paid.", "recovery", {"min_age_days": 60}),
]


def seed_rules(db: Session) -> None:
    for code, name, desc, cat, params in RULES:
        if not db.get(Rule, code):
            db.add(Rule(code=code, name=name, description=desc, category=cat))
        exists = db.scalar(select(RuleVersion).where(RuleVersion.rule_code == code, RuleVersion.version == 1))
        if not exists:
            db.add(RuleVersion(rule_code=code, version=1, params=params, active=True))


def seed_dev_admin(db: Session, email: str = "admin@pulse.local", password: str = "change-me-now") -> AppUser:
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
