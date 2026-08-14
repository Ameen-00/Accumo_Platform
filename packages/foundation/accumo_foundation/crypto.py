"""Bank-account crypto. Plaintext never hits the database."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from accumo_canonical.normalise import digits_only
from accumo_foundation.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    material = (settings.bank_encrypt_key or settings.secret_key).encode()
    digest = hashlib.sha256(material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def account_hmac(raw: str | None) -> str:
    digits = digits_only(raw)
    if not digits:
        return ""
    key = get_settings().account_hmac_key.encode()
    return hmac.new(key, digits.encode(), hashlib.sha256).hexdigest()


def encrypt_account(raw: str | None) -> str:
    if not raw:
        return ""
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_account(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def mask_account(raw: str | None) -> str:
    digits = digits_only(raw)
    if len(digits) < 4:
        return "••••"
    return "••••" + digits[-4:]
