from __future__ import annotations

import time
import uuid
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser
from accumo_foundation.config import get_settings

ph = PasswordHasher()
_attempts: dict[str, list[float]] = defaultdict(list)

COOKIE = "accumo_session"
ROLES = ("admin", "reviewer", "viewer")


def hash_password(plain: str) -> str:
    return ph.hash(plain)


def verify_password(hash_: str, plain: str) -> bool:
    try:
        ph.verify(hash_, plain)
        return True
    except VerifyMismatchError:
        return False


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="accumo-session")


def issue_session(response: Response, user: AppUser) -> None:
    settings = get_settings()
    token = _signer().dumps({"uid": str(user.id), "role": user.role})
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def rate_limit_login(ip: str) -> None:
    settings = get_settings()
    now = time.time()
    window = settings.login_window_seconds
    bucket = [t for t in _attempts[ip] if now - t < window]
    if len(bucket) >= settings.login_max_attempts:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts")
    bucket.append(now)
    _attempts[ip] = bucket


def current_user(
    db: Session = Depends(get_db),
    accumo_session: str | None = Cookie(default=None, alias=COOKIE),
) -> AppUser:
    if not accumo_session:
        raise HTTPException(status_code=401, detail="Not signed in")
    try:
        data = _signer().loads(accumo_session, max_age=get_settings().session_hours * 3600)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(AppUser, uuid.UUID(data["uid"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def require_roles(*roles: str):
    def inner(user: AppUser = Depends(current_user)) -> AppUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Not permitted")
        return user

    return inner
