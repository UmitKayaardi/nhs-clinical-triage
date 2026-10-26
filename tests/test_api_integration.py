"""
End-to-end API flow with external services mocked:
audio -> transcription -> retrieval -> LLM -> guardrail -> session -> WhatsApp alert
-> clinician feedback -> accuracy, plus the bug fixes on /sessions and 500 handling.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.api.v1.triage_routes import get_twilio_service
from app.core.config import get_settings
from app.main import app
from app.schemas.triage_schema import TriageResult
from app.services import audio_service, llm_service, retrieval_service
from app.services.llm_service import LLMGenerationError
from app.services.twilio_service import TwilioService

from tests.test_twilio_service import FakeClient, live_settings


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fake_llm(monkeypatch):
    """Returns High for chest pain, Low otherwise, and records the evidence it was shown."""
    seen = {}

    def _generate(transcript, db_context):
        seen["context"] = db_context
        severity = "High" if "chest" in transcript.lower() else "Low"
        return TriageResult(Symptoms=[transcript], Duration="2 hours", Possible_Conditions=["ACS"],
                            Severity=severity, Reasoning="Test reasoning", Required_Actions=["ECG"])

    monkeypatch.setattr(llm_service, "generate_triage_report", _generate)
    return seen


def post_audio(client, transcript, monkeypatch, **form):
    monkeypatch.setattr(audio_service, "transcribe_audio", lambda path: transcript)
    return client.post("/api/v1/process-triage",
                       files={"file": ("rec.wav", io.BytesIO(b"RIFF fake audio"), "audio/wav")}, data=form)


def test_full_flow_audio_to_accuracy(client, fake_llm, monkeypatch):
    fake = FakeClient()
    app.dependency_overrides[get_twilio_service] = lambda: TwilioService(live_settings(), client_factory=lambda: fake)

    r = post_audio(client, "Crushing chest pain for two hours", monkeypatch,
                   patient_id="P-42", age="67", gender="M", ethnicity="WHITE")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triage_result"]["Severity"] == "High"
    assert body["triage_result"]["Reasoning"] == "Test reasoning"
    assert body["evidence_cases"][0]["case_id"] == 1
    assert body["evidence_cases"][0]["similarity_score"] > 0
    assert "Chest pain" in fake_llm["context"]
    assert body["alert"]["status"] == "sent" and body["alert"]["message_sid"] == "SM123"
    assert "Case ID: " + body["session_id"] in fake.calls[0]["body"]

    sessions = client.get("/api/v1/sessions").json()["data"]
    assert sessions[0]["patient_id"] == "P-42" and sessions[0]["latest_feedback"] is None

    fb = client.post("/api/v1/feedback", json={"session_id": body["session_id"], "feedback": "correct"})
    assert fb.status_code == 201 and fb.json()["flagged_for_review"] is False

    acc = client.get("/api/v1/admin/accuracy").json()
    assert acc["accuracy_30d"] == 1.0 and acc["reviewed_sessions"] == 1
    assert client.get("/api/v1/sessions").json()["data"][0]["latest_feedback"] == "correct"


def test_low_severity_does_not_alert(client, fake_llm, monkeypatch):
    r = post_audio(client, "Runny nose", monkeypatch)
    assert r.status_code == 200
    assert r.json()["alert"] is None
    assert client.get("/api/v1/alerts").json()["count"] == 0


def test_high_severity_in_test_mode_is_mocked_and_logged(client, fake_llm, monkeypatch):
    r = post_audio(client, "chest pain", monkeypatch)
    assert r.json()["alert"]["status"] == "mocked"
    alerts = client.get("/api/v1/alerts").json()["data"]
    assert alerts[0]["alert_type"] == "whatsapp_triage" and alerts[0]["session_id"] == r.json()["session_id"]


def test_structured_intake_with_vitals(client, fake_llm):
    r = client.post("/api/v1/process-triage/structured", json={
        "chief_complaint": "short of breath and chest tight",
        "vitals": {"o2sat": 86, "resp_rate": 28, "heart_rate": 118},
        "gender": "F", "age": 54,
    })
    assert r.status_code == 200, r.text
    assert "Vitals: " in fake_llm["context"]
    assert client.get("/api/v1/sessions").json()["data"][0]["intake_mode"] == "structured"


def test_invalid_patient_context_is_422(client, fake_llm, monkeypatch):
    assert post_audio(client, "chest pain", monkeypatch, gender="Male").status_code == 422
    r = client.post("/api/v1/process-triage/structured", json={"chief_complaint": "x"})
    assert r.status_code == 422


def test_unsupported_audio_and_silent_audio(client, monkeypatch):
    r = client.post("/api/v1/process-triage", files={"file": ("rec.txt", io.BytesIO(b"x"), "text/plain")})
    assert r.status_code == 400

    def silent(path):
        raise audio_service.TranscriptionError("No speech detected in the recording.")
    monkeypatch.setattr(audio_service, "transcribe_audio", silent)
    r = client.post("/api/v1/process-triage", files={"file": ("rec.wav", io.BytesIO(b"x"), "audio/wav")})
    assert r.status_code == 422 and "No speech" in r.json()["detail"]


def test_llm_failure_is_502(client, monkeypatch):
    def broken(transcript, ctx):
        raise LLMGenerationError("LLM output was not valid JSON")
    monkeypatch.setattr(llm_service, "generate_triage_report", broken)
    assert post_audio(client, "chest pain", monkeypatch).status_code == 502


def test_unexpected_error_returns_generic_500(client, fake_llm, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret connection string postgres://user:pw@host")
    monkeypatch.setattr(retrieval_service, "find_similar_cases", boom)
    r = post_audio(client, "chest pain", monkeypatch)
    assert r.status_code == 500
    assert r.json() == {"error": "Internal server error"}
    assert "secret" not in r.text


def test_sessions_filter_and_order(client, fake_llm, monkeypatch):
    post_audio(client, "chest pain one", monkeypatch)
    post_audio(client, "runny nose", monkeypatch)
    post_audio(client, "chest pain two", monkeypatch)

    data = client.get("/api/v1/sessions").json()["data"]
    assert [d["transcript"] for d in data] == ["chest pain two", "runny nose", "chest pain one"]

    high = client.get("/api/v1/sessions", params={"severity": "High"}).json()
    assert high["count"] == 2 and all(d["severity"] == "High" for d in high["data"])
    assert client.get("/api/v1/sessions", params={"severity": "Critical"}).status_code == 422


def test_admin_key_protects_monitoring_routes(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", "s3cret")
    assert client.get("/api/v1/admin/accuracy").status_code == 401
    assert client.get("/api/v1/admin/accuracy", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/admin/accuracy", headers={"X-Admin-Key": "s3cret"}).status_code == 200
    assert client.get("/api/v1/sessions").status_code == 200  # dashboard read stays open


def test_feedback_unknown_session_is_404(client):
    r = client.post("/api/v1/feedback",
                    json={"session_id": "00000000-0000-0000-0000-000000000000", "feedback": "correct"})
    assert r.status_code == 404


def test_pms_report_drift_and_alert_endpoints(client, fake_llm, monkeypatch):
    post_audio(client, "chest pain", monkeypatch)

    r = client.get("/api/v1/admin/pms-report", params={"month": "2026-10"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0] == "date,total_sessions,reviewed,correct,hallucinations,accuracy_%,alerts"
    assert client.get("/api/v1/admin/pms-report", params={"month": "2026-13"}).status_code == 422

    drift = client.get("/api/v1/admin/drift").json()
    for key in ("drift_score", "bias_scores_by_demographic", "trend_graph_data", "drift_detected", "bias_detected"):
        assert key in drift

    created = client.post("/api/v1/alerts", json={"alert_type": "manual", "severity": "warning",
                                                  "message": "Check the scanner"})
    assert created.status_code == 201
    alert_id = created.json()["id"]
    assert client.post(f"/api/v1/alerts/{alert_id}/acknowledge").json()["acknowledged"] is True
    unacked = client.get("/api/v1/alerts", params={"unacknowledged_only": True}).json()["data"]
    assert alert_id not in [a["id"] for a in unacked]
