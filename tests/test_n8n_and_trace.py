"""WP5 n8n orchestration with Twilio fallback; WP4 agent trace in the API; WP2/WP3 response fields."""

import json
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.v1.triage_routes import get_n8n_orchestrator
from app.core.config import get_settings
from app.main import app
from app.models.monitoring_models import AlertLog
from app.services import llm_service
from app.services.n8n_service import N8nOrchestrator, N8nUnavailable

VALID = json.dumps({"Symptoms": ["chest pain"], "Duration": "1 hour", "Possible_Conditions": ["ACS"],
                    "Severity": "Low", "Confidence": "Medium", "Reasoning": "Looks minor.",
                    "Required_Actions": ["Observe"]})


def n8n_settings(**overrides):
    values = dict(N8N_WEBHOOK_URL="http://n8n.test/webhook/triage-alert", N8N_WEBHOOK_SECRET="hook-secret",
                  N8N_MAX_RETRIES=2, N8N_TIMEOUT_SECONDS=5.0)
    values.update(overrides)
    return get_settings().model_copy(update=values)


class FakePost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return SimpleNamespace(status_code=status, json=lambda: body)


def test_n8n_success_sends_secret_header_and_payload():
    post = FakePost([(200, {"status": "sent", "channel": "n8n", "message_sid": "SM9"})])
    out = N8nOrchestrator(n8n_settings(), post=post, sleep=lambda s: None).send({"session_id": "abc", "severity": "High"})
    assert out == {"status": "sent", "channel": "n8n", "message_sid": "SM9"}
    call = post.calls[0]
    assert call["headers"]["X-Webhook-Secret"] == "hook-secret"
    assert call["timeout"] == 5.0 and call["json"]["severity"] == "High"


def test_n8n_retries_then_raises_when_down():
    post = FakePost([requests.ConnectionError(), (503, {}), requests.Timeout()])
    with pytest.raises(N8nUnavailable):
        N8nOrchestrator(n8n_settings(), post=post, sleep=lambda s: None).send({})
    assert len(post.calls) == 3  # 1 attempt + 2 retries


def test_n8n_not_configured():
    orch = N8nOrchestrator(n8n_settings(N8N_WEBHOOK_URL=None))
    assert not orch.configured
    with pytest.raises(N8nUnavailable):
        orch.send({})


@pytest.fixture
def client(monkeypatch):
    # Agent 3 returns "Low" so the NEWS2 safety net has something to raise.
    monkeypatch.setattr(llm_service, "groq_completion",
                        lambda messages, params: (VALID, {"latency_ms": 3.0, "usage": {"total_tokens": 50}}))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def structured(client, **extra):
    body = {"chief_complaint": "chest pain and short of breath",
            "vitals": {"heart_rate": 125, "resp_rate": 28, "o2sat": 90, "sbp": 95, "dbp": 60},
            "age": 70, "gender": "M"}
    body.update(extra)
    return client.post("/api/v1/process-triage/structured", json=body)


def test_structured_triage_returns_trace_news2_override_and_evidence(client, db):
    app.dependency_overrides[get_n8n_orchestrator] = lambda: N8nOrchestrator(n8n_settings(N8N_WEBHOOK_URL=None))
    r = structured(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_severity"] == "Low"
    assert body["triage_result"]["Severity"] == "High"           # raised by NEWS2
    assert body["safety_override"] is True and body["news2_score"] >= 7
    assert body["evidence_strength"] in ("strong", "moderate", "weak")
    assert body["guardrail_attempts"] == 1
    agents = [s["agent_no"] for s in body["trace"]]
    assert agents == [1, 2, 3, 4, 4, 0, 5]
    assert body["alert"]["channel"] == "mocked"                  # no n8n, Twilio in test mode

    stored = client.get(f"/api/v1/sessions/{body['session_id']}/trace").json()
    assert stored["count"] == len(body["trace"]) and stored["steps"][1]["agent_name"] == "Evidence Retrieval"
    listed = client.get("/api/v1/sessions").json()["data"][0]
    assert listed["safety_override"] is True and listed["has_trace"] is True


def test_alert_goes_through_n8n_when_configured(client, db):
    post = FakePost([(200, {"status": "mocked", "channel": "n8n", "message_sid": None})])
    app.dependency_overrides[get_n8n_orchestrator] = lambda: N8nOrchestrator(n8n_settings(), post=post,
                                                                             sleep=lambda s: None)
    body = structured(client).json()
    assert body["alert"]["channel"] == "n8n" and body["alert"]["status"] == "mocked"
    sent = post.calls[0]["json"]
    assert sent["severity"] == "High" and sent["test_mode"] is True and "news2_score" in sent
    assert db.query(AlertLog).filter(AlertLog.channel == "n8n").count() == 1


def test_n8n_down_falls_back_to_twilio(client, db):
    post = FakePost([requests.ConnectionError()] * 3)
    app.dependency_overrides[get_n8n_orchestrator] = lambda: N8nOrchestrator(n8n_settings(), post=post,
                                                                             sleep=lambda s: None)
    body = structured(client).json()
    assert body["alert"]["channel"] == "mocked"                   # Twilio fallback, test mode
    agent5 = [s for s in body["trace"] if s["agent_no"] == 5][0]
    assert agent5["output"]["fallback_from_n8n"] is True and "n8n_error" in agent5["input"]


def test_trace_endpoint_errors(client):
    assert client.get("/api/v1/sessions/not-a-uuid/trace").status_code == 422
    assert client.get("/api/v1/sessions/00000000-0000-0000-0000-000000000000/trace").status_code == 404


def test_feedback_and_drift_add_agent_6_and_7_trace_steps(client):
    app.dependency_overrides[get_n8n_orchestrator] = lambda: N8nOrchestrator(n8n_settings(N8N_WEBHOOK_URL=None))
    sid = structured(client).json()["session_id"]
    assert client.post("/api/v1/feedback", json={"session_id": sid, "feedback": "correct"}).status_code == 201
    steps = client.get(f"/api/v1/sessions/{sid}/trace").json()["steps"]
    assert steps[-1]["agent_no"] == 6 and steps[-1]["output"]["verdict"] == "correct"
    drift = client.get("/api/v1/admin/drift?persist=false").json()
    assert drift["trace"][0]["agent_no"] == 7


def test_system_health_never_leaks_errors(client, monkeypatch):
    def broken():
        raise RuntimeError("gsk_secret_key_text")
    monkeypatch.setattr(llm_service, "_get_client", broken)
    r = client.get("/api/v1/admin/system-health")
    assert r.status_code == 200
    body = r.json()
    assert body["groq"]["reachable"] is False and "secret" not in r.text
    assert body["database"]["rows"]["ed_stays (MIMIC KB)"] == 8
    assert body["models"]["agent3_llm"] == "openai/gpt-oss-20b"
