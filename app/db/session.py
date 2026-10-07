"""
Database session management.

Provides:
- `engine`: the SQLAlchemy engine, built from Settings.DATABASE_URL.
- `SessionLocal`: a session factory bound to that engine.
- `get_db`: a FastAPI dependency that yields a session per-request and
  guarantees it is closed afterwards, even if the request raises.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import get_settings

settings = get_settings()

# If the database URL starts with sqlite, disable the thread lock
# so FastAPI (Uvicorn) can access the same file concurrently.
engine_kwargs = {"pool_pre_ping": True, "future": True}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a scoped database session.
    Usage: `db: Session = Depends(get_db)` in an endpoint signature.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()