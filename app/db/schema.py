"""
Idempotent schema bootstrap, run on application startup.

The Hugging Face Space ships a pre-built SQLite file (triage_data.db) and
has no step where `alembic upgrade head` can run. This helper brings any
existing database up to the current models without touching data:
- creates tables that don't exist yet (feedback, alert log, drift metrics);
- adds the new nullable columns to triage_sessions if they are missing.

Alembic migrations remain the source of truth for managed deployments
(Postgres via docker-compose); this is the safety net for file-based ones.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.models.mimic_models import TriageSession

logger = logging.getLogger(__name__)


def ensure_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing = {col["name"] for col in inspector.get_columns(TriageSession.__tablename__)}
    missing = [col for col in TriageSession.__table__.columns if col.name not in existing]
    if not missing:
        return

    with engine.begin() as conn:
        for col in missing:
            col_type = col.type.compile(dialect=engine.dialect)
            logger.info("Adding missing column triage_sessions.%s (%s)", col.name, col_type)
            conn.execute(text(f"ALTER TABLE {TriageSession.__tablename__} ADD COLUMN {col.name} {col_type}"))
