"""add agent trace, evidence strength and NEWS2 safety-net fields (CN7050 WP2-WP5)

Revision ID: d8e9f0a1b2c3
Revises: c7d1e2f3a4b5
Create Date: 2026-11-21 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_SESSION_COLUMNS = [
    sa.Column('llm_severity', sa.String(length=10), nullable=True),
    sa.Column('news2_score', sa.Integer(), nullable=True),
    sa.Column('safety_override', sa.Boolean(), nullable=True),
    sa.Column('override_reason', sa.Text(), nullable=True),
    sa.Column('evidence_strength', sa.String(length=10), nullable=True),
    sa.Column('low_evidence', sa.Boolean(), nullable=True),
    sa.Column('top_similarity', sa.Float(), nullable=True),
    sa.Column('vitals_json', sa.Text(), nullable=True),
    sa.Column('agent_trace', sa.Text(), nullable=True),
]


def upgrade() -> None:
    for column in _NEW_SESSION_COLUMNS:
        op.add_column('triage_sessions', column)
    op.add_column('alert_log', sa.Column('channel', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('alert_log', 'channel')
    for column in reversed(_NEW_SESSION_COLUMNS):
        op.drop_column('triage_sessions', column.name)
