from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from accumo_canonical.db import engine, get_db, init_engine
from accumo_canonical.models import Base
from accumo_foundation.config import get_settings
from accumo_pulse.seed import seed_dev_admin, seed_rules

from app.routers import auth, health


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.env == "prod" and settings.secret_key.startswith("dev-only"):
        raise RuntimeError("SECRET_KEY must be set in production")
    init_engine()
    assert engine is not None
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed_rules(db)
        if settings.env == "dev":
            seed_dev_admin(db)
        db.commit()
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Accumo",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", f"https://{settings.public_host}"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    return app


app = create_app()
