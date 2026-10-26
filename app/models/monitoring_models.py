"""
SQLAlchemy ORM models for post-deployment monitoring (Agents 5, 6 and 7).

These tables are written by the live system, never by the MIMIC import:
- TriageSessionFeedback: a clinician's verdict on one TriageSession
  (Agent 6 accuracy + hallucination tracking).
- AlertLog: every alert the system raised -- WhatsApp dispatches and
  their failures (Agent 5), and drift/bias/accuracy alerts (Agent 7).
- DriftMetrics: a snapshot of the monitoring statistics each time the
  drift check runs, so trends can be audited later.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class FeedbackVerdict(str, enum.Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"


class TriageSessionFeedback(Base):
    """
    One clinician review of a triage session. A session can be reviewed
    more than once; monitoring always uses the most recent review.
    An "incorrect" verdict flags the session as a suspected hallucination
    for follow-up review.
    """

    __tablename__ = "triage_session_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("triage_sessions.id"), nullable=False, index=True)
    feedback = Column(SAEnum(FeedbackVerdict), nullable=False)
    feedback_notes = Column(Text, nullable=True)
    reviewed_by = Column(String(100), nullable=True)
    flagged_for_review = Column(Boolean, default=False, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AlertLog(Base):
    """Audit trail of every alert raised or attempted."""

    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("triage_sessions.id"), nullable=True, index=True)
    # e.g. whatsapp_triage, whatsapp_failure, performance_drift, data_drift, bias, manual
    alert_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False)  # info | warning | critical
    message = Column(Text, nullable=False)
    status = Column(String(30), nullable=True)      # sent | mocked | failed | logged | emailed
    external_id = Column(String(64), nullable=True)  # Twilio message SID
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    acknowledged = Column(Boolean, default=False, nullable=False)


class DriftMetrics(Base):
    """One run of the Agent 7 drift and bias check."""

    __tablename__ = "drift_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    accuracy_30d = Column(Float, nullable=True)
    hallucination_rate = Column(Float, nullable=True)
    drift_score = Column(Float, nullable=True)
    bias_by_demographic = Column(Text, nullable=True)  # JSON-encoded dict
    retraining_needed = Column(Boolean, default=False, nullable=False)
