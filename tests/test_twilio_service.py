"""Agent 5 -- WhatsApp alerting. Twilio is always mocked; nothing is sent."""

from types import SimpleNamespace

from app.core.config import get_settings
from app.models.monitoring_models import AlertLog
from app.services.twilio_service import TwilioService


class FakeTwilioError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


class FakeClient:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(sid="SM123")


def live_settings(**overrides):
    values = dict(
        TWILIO_TEST_MODE=False,
        TWILIO_ACCOUNT_SID="ACtest",
        TWILIO_AUTH_TOKEN="token",
        TWILIO_PHONE_NUMBER="+14155238886",
        DOCTOR_WHATSAPP_NUMBER="+447700900123",
        TWILIO_MAX_RETRIES=3,
        TWILIO_RETRY_BACKOFF_SECONDS=1.0,
    )
    values.update(overrides)
    return get_settings().model_copy(update=values)


def make_session(db):
    from app.models.mimic_models import SeverityLevel, TriageSession
    s = TriageSession(transcript="chest pain", severity=SeverityLevel.HIGH)
    db.add(s)
    db.commit()
    return str(s.id)


def test_message_format_matches_spec():
    body = TwilioService.format_message("High", "Chest pain", "abc-123", "P-1", "Red flags present")
    assert body.startswith("🚨 TRIAGE ALERT — PRIORITY: HIGH\nChief Complaint: Chest pain\nCase ID: abc-123")
    assert "Patient ID: P-1" in body and "Reasoning: Red flags present" in body


def test_test_mode_mocks_and_logs(db):
    sid = make_session(db)
    service = TwilioService()  # conftest forces TWILIO_TEST_MODE
    assert not service.is_live
    result = service.send_whatsapp_alert("P-1", "High", "why", "Chest pain", sid, db=db)
    assert result["status"] == "mocked" and result["message_sid"] is None
    alert = db.query(AlertLog).one()
    assert (alert.alert_type, alert.status, str(alert.session_id)) == ("whatsapp_triage", "mocked", sid)


def test_missing_credentials_never_go_live():
    assert not TwilioService(live_settings(TWILIO_AUTH_TOKEN=None)).is_live


def test_live_send_uses_whatsapp_numbers_and_logs_sid(db):
    sid = make_session(db)
    client = FakeClient()
    service = TwilioService(live_settings(), client_factory=lambda: client)
    result = service.send_whatsapp_alert(None, "High", "why", "Chest pain", sid, db=db)
    assert result["status"] == "sent" and result["message_sid"] == "SM123"
    call = client.calls[0]
    assert call["from_"] == "whatsapp:+14155238886" and call["to"] == "whatsapp:+447700900123"
    assert db.query(AlertLog).one().external_id == "SM123"


def test_transient_errors_are_retried_with_backoff(db):
    sid = make_session(db)
    sleeps = []
    client = FakeClient(failures=[FakeTwilioError(503), ConnectionError("reset")])
    service = TwilioService(live_settings(), client_factory=lambda: client, sleep=sleeps.append)
    result = service.send_whatsapp_alert(None, "High", "", "Chest pain", sid, db=db)
    assert result["status"] == "sent"
    assert len(client.calls) == 3 and sleeps == [1.0, 2.0]


def test_client_errors_fail_fast_and_are_logged(db):
    sid = make_session(db)
    client = FakeClient(failures=[FakeTwilioError(400)])
    service = TwilioService(live_settings(), client_factory=lambda: client, sleep=lambda s: None)
    result = service.send_whatsapp_alert(None, "High", "", "Chest pain", sid, db=db)
    assert result["status"] == "failed" and len(client.calls) == 1
    alert = db.query(AlertLog).one()
    assert alert.alert_type == "whatsapp_failure" and alert.status == "failed"


def test_exhausted_retries_are_logged(db):
    sid = make_session(db)
    client = FakeClient(failures=[FakeTwilioError(500)] * 3)
    service = TwilioService(live_settings(), client_factory=lambda: client, sleep=lambda s: None)
    assert service.send_whatsapp_alert(None, "High", "", "x", sid, db=db)["status"] == "failed"
    assert len(client.calls) == 3


def test_only_configured_severities_alert():
    service = TwilioService()
    assert service.should_alert("High")
    assert not service.should_alert("Medium") and not service.should_alert("Low")
