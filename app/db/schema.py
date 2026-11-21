"""
Idempotent schema bootstrap, run on application startup.

The Hugging Face Space ships a pre-built SQLite file (triage_data.db) and
has no step where `alembic upgrade head` can run. This helper brings any
existing database up to the current models without touching data:
- creates tables that don't exist yet (feedback, alert log, drift metrics);
- adds new nullable columns to existing tables if they are missing
  (triage_sessions: WP2-WP4 fields and agent_trace; alert_log: channel).

Alembic migrations remain the source of truth for managed deployments
(Postgres via docker-compose); this is the safety net for file-based ones.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.models.mimic_models import TriageSession
from app.models.monitoring_models import AlertLog

logger = logging.getLogger(__name__)

_EVOLVING_TABLES = (TriageSession.__table__, AlertLog.__table__)


def ensure_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    for table in _EVOLVING_TABLES:
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        missing = [col for col in table.columns if col.name not in existing and col.nullable]
        if not missing:
            continue
        with engine.begin() as conn:
            for col in missing:
                col_type = col.type.compile(dialect=engine.dialect)
                logger.info("Adding missing column %s.%s (%s)", table.name, col.name, col_type)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}"))
