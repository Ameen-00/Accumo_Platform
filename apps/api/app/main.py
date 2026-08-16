from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from accumo_canonical.db import get_db, init_engine
from accumo_canonical.models import Base
from accumo_foundation.config import get_settings
from accumo_pulse.seed import seed_dev_admin, seed_rules

from app.routers import auth, exceptions, health, identities, imports, intake, reports, runs


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.env == "prod" and settings.secret_key.startswith("dev-only"):
        raise RuntimeError("SECRET_KEY must be set in production")
    bound = init_engine()
    Base.metadata.create_all(bind=bound)
    db = next(get_db())
    try:
        seed_rules(db)
        if settings.env in {"dev", "staging"}:
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
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "That request failed."
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": "That request was incomplete. Check the files and try again."},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "Pulse hit an unexpected error while working on this drop. "
                    "Nothing was booked. Press Review findings again. "
                    "If it fails twice, drop the files once more."
                )
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(imports.router)
    app.include_router(intake.router)
    app.include_router(identities.router)
    app.include_router(runs.router)
    app.include_router(exceptions.router)
    app.include_router(reports.router)
    web = Path(__file__).resolve().parents[3] / "web" / "dist"
    if web.is_dir():
        index = web / "index.html"

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            target = web / full_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(index)

    return app


app = create_app()
