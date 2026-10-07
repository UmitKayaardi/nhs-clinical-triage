"""
Central import hub for the SQLAlchemy Declarative Base.

Alembic's `env.py` imports `Base` from here (and, transitively, every
model module) so that `alembic revision --autogenerate` can detect the
full schema. New model modules should always be imported below.
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import model modules so they register with Base.metadata.
# Keep this import at the bottom to avoid circular imports.
from app.models import mimic_models  # noqa: E402,F401
