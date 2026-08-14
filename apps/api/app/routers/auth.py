from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from accumo_canonical.db import get_db
from accumo_canonical.models import AppUser
from accumo_foundation.audit import write
from accumo_foundation.auth import (
    clear_session,
    current_user,
    issue_session,
    rate_limit_login,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "0.0.0.0"
    rate_limit_login(ip)
    user = db.scalar(select(AppUser).where(AppUser.email == body.email.lower()))
    if not user or not user.is_active or not verify_password(user.password_hash, body.password):
        write(db, action="auth.login_failed", detail={"email_domain": body.email.split("@")[-1]}, ip=ip)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    issue_session(response, user)
    write(
        db,
        action="auth.login",
        actor_id=user.id,
        organisation_id=user.organisation_id,
        object_type="app_user",
        object_id=user.id,
        ip=ip,
    )
    db.commit()
    return {"id": str(user.id), "role": user.role, "name": user.full_name}


@router.post("/logout")
def logout(response: Response, user: AppUser = Depends(current_user), db: Session = Depends(get_db)):
    clear_session(response)
    write(db, action="auth.logout", actor_id=user.id, organisation_id=user.organisation_id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: AppUser = Depends(current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.full_name,
        "role": user.role,
        "organisation_id": str(user.organisation_id) if user.organisation_id else None,
    }
