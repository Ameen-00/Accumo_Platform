from fastapi import APIRouter

from accumo_foundation.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    s = get_settings()
    return {
        "ok": True,
        "product": "accumo-platform",
        "country_code": s.country_code,
        "base_currency": s.base_currency,
        "env": s.env,
    }
