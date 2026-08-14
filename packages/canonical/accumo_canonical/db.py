from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from accumo_foundation.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine():
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=8,
        max_overflow=8,
    )


engine = None
SessionLocal = None


def init_engine() -> None:
    global engine, SessionLocal
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        init_engine()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
