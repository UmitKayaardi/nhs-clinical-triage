"""add monitoring tables and triage session context (agents 5-7)

Revision ID: c7d1e2f3a4b5
Revises: b46bda9cf2c9
Create Date: 2026-10-26 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c7d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b46bda9cf2c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_SESSION_COLUMNS = [
    sa.Column('chief_complaint', sa.Text(), nullable=True),
    sa.Column('reasoning', sa.Text(), nullable=True),
    sa.Column('required_actions', sa.Text(), nullable=True),
    sa.Column('evidence_scores', sa.Text(), nullable=True),
    sa.Column('intake_mode', sa.String(length=20), nullable=True),
    sa.Column('patient_id', sa.String(length=64), nullable=True),
    sa.Column('age', sa.Integer(), nullable=True),
    sa.Column('gender', sa.String(length=1), nullable=True),
    sa.Column('ethnicity', sa.String(length=100), nullable=True),
]


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('triage_sessions') as batch_op:
        for column in _NEW_SESSION_COLUMNS:
            batch_op.add_column(column.copy())
        batch_op.create_index('ix_triage_sessions_patient_id', ['patient_id'])
        batch_op.create_index('ix_triage_sessions_created_at', ['created_at'])

    op.create_table(
        'triage_session_feedback',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feedback', sa.Enum('CORRECT', 'INCORRECT', name='feedbackverdict'), nullable=False),
        sa.Column('feedback_notes', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.Column('flagged_for_review', sa.Boolean(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['triage_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_triage_session_feedback_session_id', 'triage_session_feedback', ['session_id'])
    op.create_index('ix_triage_session_feedback_timestamp', 'triage_session_feedback', ['timestamp'])

    op.create_table(
        'alert_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('alert_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('external_id', sa.String(length=64), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('acknowledged', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['triage_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alert_log_session_id', 'alert_log', ['session_id'])
    op.create_index('ix_alert_log_alert_type', 'alert_log', ['alert_type'])
    op.create_index('ix_alert_log_timestamp', 'alert_log', ['timestamp'])

    op.create_table(
        'drift_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('accuracy_30d', sa.Float(), nullable=True),
        sa.Column('hallucination_rate', sa.Float(), nullable=True),
        sa.Column('drift_score', sa.Float(), nullable=True),
        sa.Column('bias_by_demographic', sa.Text(), nullable=True),
        sa.Column('retraining_needed', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_drift_metrics_timestamp', 'drift_metrics', ['timestamp'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_drift_metrics_timestamp', table_name='drift_metrics')
    op.drop_table('drift_metrics')
    op.drop_index('ix_alert_log_timestamp', table_name='alert_log')
    op.drop_index('ix_alert_log_alert_type', table_name='alert_log')
    op.drop_index('ix_alert_log_session_id', table_name='alert_log')
    op.drop_table('alert_log')
    op.drop_index('ix_triage_session_feedback_timestamp', table_name='triage_session_feedback')
    op.drop_index('ix_triage_session_feedback_session_id', table_name='triage_session_feedback')
    op.drop_table('triage_session_feedback')
    sa.Enum(name='feedbackverdict').drop(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('triage_sessions') as batch_op:
        batch_op.drop_index('ix_triage_sessions_created_at')
        batch_op.drop_index('ix_triage_sessions_patient_id')
        for column in reversed(_NEW_SESSION_COLUMNS):
            batch_op.drop_column(column.name)
