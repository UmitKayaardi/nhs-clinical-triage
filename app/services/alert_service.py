"""
Shared alert plumbing for Agents 5, 6 and 7.

Every alert the system raises -- a WhatsApp dispatch, a failed dispatch,
a drift or bias warning, or a manual alert posted to /api/v1/alerts --
is written to the AlertLog table so there is a single audit trail.
Critical alerts can additionally be emailed to the administrator when
SMTP settings are configured; otherwise they are logged only.
"""

import logging
import smtplib
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Optional, Union

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.monitoring_models import AlertLog

logger = logging.getLogger(__name__)


def _as_uuid(value: Union[str, uuid.UUID, None]) -> Optional[uuid.UUID]:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def log_alert(
    db: Session,
    alert_type: str,
    severity: str,
    message: str,
    session_id: Union[str, uuid.UUID, None] = None,
    status: Optional[str] = "logged",
    external_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> AlertLog:
    """Persists one alert. Commits immediately so the record survives a later failure."""
    alert = AlertLog(
        session_id=_as_uuid(session_id),
        alert_type=alert_type,
        severity=severity,
        message=message,
        status=status,
        external_id=external_id,
        timestamp=timestamp or datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def recent_alert_exists(db: Session, alert_type: str, within_hours: int = 24,
                        now: Optional[datetime] = None) -> bool:
    """Used to avoid re-raising the same monitoring alert on every dashboard refresh."""
    since = (now or datetime.utcnow()) - timedelta(hours=within_hours)
    return (
        db.query(AlertLog.id)
        .filter(AlertLog.alert_type == alert_type, AlertLog.timestamp >= since)
        .first()
        is not None
    )


def email_admin(subject: str, body: str) -> bool:
    """
    Sends a plain-text email to ADMIN_EMAIL. Returns False (and only logs)
    when SMTP is not configured or the send fails -- alerting must never
    break the request that triggered it.
    """
    settings = get_settings()
    if not (settings.SMTP_HOST and settings.ADMIN_EMAIL):
        logger.warning("Admin email not configured; alert logged only: %s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"[NHS Triage] {subject}"
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME or settings.ADMIN_EMAIL
    msg["To"] = settings.ADMIN_EMAIL
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception:
        logger.exception("Failed to email admin alert: %s", subject)
        return False


def raise_alert(
    db: Session,
    alert_type: str,
    severity: str,
    message: str,
    session_id: Union[str, uuid.UUID, None] = None,
    timestamp: Optional[datetime] = None,
) -> AlertLog:
    """Logs an alert and, for critical ones, emails the admin."""
    status = "logged"
    if severity == "critical" and email_admin(alert_type.replace("_", " ").title(), message):
        status = "emailed"
    return log_alert(db, alert_type, severity, message, session_id=session_id, status=status, timestamp=timestamp)
