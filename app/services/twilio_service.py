"""
Agent 5 -- Orchestrator & Action (Twilio WhatsApp).

Sends an instant WhatsApp alert to the on-call clinician when a triage
session is classified at an alerting severity (High by default, see
ALERT_ON_SEVERITIES). Every attempt is written to AlertLog: successful
sends as `whatsapp_triage`, and exhausted retries as `whatsapp_failure`.

Safety defaults:
- If any Twilio credential is missing, or TWILIO_TEST_MODE is true, the
  message is NOT sent; it is logged with status "mocked". CI, local
  development and the public demo therefore never text a real phone.
- Transient failures (network errors, HTTP 429/5xx) are retried with
  exponential backoff. Client errors (bad number, auth failure) are not
  retried, since repeating them cannot succeed.
- Failures never propagate to the caller: the triage report is already
  saved and must still be returned to the clinician.
"""

import logging
import time
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.alert_service import log_alert

logger = logging.getLogger(__name__)

ALERT_TEMPLATE = (
    "🚨 TRIAGE ALERT — PRIORITY: {level}\n"
    "Chief Complaint: {chief_complaint}\n"
    "Case ID: {session_id}\n"
    "Patient ID: {patient_id}\n"
    "Reasoning: {reasoning}\n"
    "AI decision support only — clinician review required."
)


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status", None)
    if status is None:
        return True  # network/timeout errors carry no HTTP status
    return status == 429 or status >= 500


class TwilioService:
    def __init__(self, settings: Optional[Settings] = None, client_factory: Optional[Callable] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings or get_settings()
        self._client_factory = client_factory
        self._client = None
        self._sleep = sleep

    @property
    def is_live(self) -> bool:
        s = self.settings
        return bool(
            not s.TWILIO_TEST_MODE
            and s.TWILIO_ACCOUNT_SID and s.TWILIO_AUTH_TOKEN
            and s.TWILIO_PHONE_NUMBER and s.DOCTOR_WHATSAPP_NUMBER
        )

    def should_alert(self, triage_level: str) -> bool:
        return triage_level in self.settings.ALERT_ON_SEVERITIES

    def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                from twilio.rest import Client  # imported lazily so tests/demo don't need credentials
                self._client = Client(self.settings.TWILIO_ACCOUNT_SID, self.settings.TWILIO_AUTH_TOKEN)
        return self._client

    @staticmethod
    def format_message(triage_level: str, chief_complaint: str, session_id: str,
                       patient_id: Optional[str] = None, reasoning: Optional[str] = None) -> str:
        complaint = (chief_complaint or "Not stated").strip()
        if len(complaint) > 300:
            complaint = complaint[:297] + "..."
        why = (reasoning or "Not provided").strip()
        if len(why) > 500:
            why = why[:497] + "..."
        return ALERT_TEMPLATE.format(
            level=str(triage_level).upper(),
            chief_complaint=complaint,
            session_id=session_id,
            patient_id=patient_id or "Not provided",
            reasoning=why,
        )

    @staticmethod
    def _whatsapp(number: str) -> str:
        return number if number.startswith("whatsapp:") else f"whatsapp:{number}"

    def send_whatsapp_alert(
        self,
        patient_id: Optional[str],
        triage_level: str,
        reasoning: Optional[str],
        chief_complaint: str,
        session_id: str,
        db: Optional[Session] = None,
    ) -> dict:
        """
        Sends (or mocks) the alert and records the outcome in AlertLog when `db` is given.

        Returns:
            {"message_sid": str | None, "status": "sent" | "mocked" | "failed", "timestamp": ISO-8601}
        """
        body = self.format_message(triage_level, chief_complaint, session_id, patient_id, reasoning)
        now = datetime.utcnow()

        if not self.is_live:
            logger.info("Twilio not live (test mode or missing credentials); mocking alert for %s", session_id)
            result = {"message_sid": None, "status": "mocked", "timestamp": now.isoformat()}
            if db is not None:
                log_alert(db, "whatsapp_triage", "critical", body, session_id=session_id, status="mocked")
            return result

        last_error: Optional[Exception] = None
        for attempt in range(1, self.settings.TWILIO_MAX_RETRIES + 1):
            try:
                message = self._get_client().messages.create(
                    from_=self._whatsapp(self.settings.TWILIO_PHONE_NUMBER),
                    to=self._whatsapp(self.settings.DOCTOR_WHATSAPP_NUMBER),
                    body=body,
                )
                result = {
                    "message_sid": message.sid,
                    "status": "sent",
                    "timestamp": datetime.utcnow().isoformat(),
                }
                if db is not None:
                    log_alert(db, "whatsapp_triage", "critical", body, session_id=session_id,
                              status="sent", external_id=message.sid)
                return result
            except Exception as exc:  # twilio raises TwilioRestException plus transport errors
                last_error = exc
                retryable = _is_retryable(exc)
                logger.warning("WhatsApp alert attempt %d/%d failed for %s: %s",
                               attempt, self.settings.TWILIO_MAX_RETRIES, session_id, exc)
                if not retryable or attempt == self.settings.TWILIO_MAX_RETRIES:
                    break
                self._sleep(self.settings.TWILIO_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

        logger.error("WhatsApp alert failed for session %s: %s", session_id, last_error)
        if db is not None:
            log_alert(db, "whatsapp_failure", "critical",
                      f"WhatsApp alert could not be delivered: {last_error}\n---\n{body}",
                      session_id=session_id, status="failed")
        return {"message_sid": None, "status": "failed", "timestamp": datetime.utcnow().isoformat()}
