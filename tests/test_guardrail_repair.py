"""WP3 -- Agent 4 guardrail checks and the Agent 4 -> Agent 3 repair loop; WP2 prompt flag."""

import json

import pytest

from app.services import llm_service
from app.services.llm_service import GuardrailRejection, LLMGenerationError, generate_triage_report, guardrail_validate
from app.services.trace import AgentTrace

VALID = json.dumps({"Symptoms": ["chest pain"], "Duration": "1 hour", "Possible_Conditions": ["ACS"],
                    "Severity": "High", "Confidence": "High", "Reasoning": "Cardiac features.",
                    "Required_Actions": ["ECG"]})


def scripted(*outputs):
    calls = []

    def fn(messages, params):
        calls.append(messages)
        return outputs[len(calls) - 1], {"latency_ms": 5.0, "usage": {"total_tokens": 100}, "cached": False}

    fn.calls = calls
    return fn


@pytest.mark.parametrize("raw,reason", [
    ("", "empty"),
    ("not json", "not valid JSON"),
    ("[1, 2]", "single JSON object"),
    (json.dumps({"Reasoning": "x"}), "Severity is missing"),
    (json.dumps({"Severity": "Critical", "Reasoning": "x"}), "schema validation failed"),
    (json.dumps({"Severity": "High", "Reasoning": "  "}), "Reasoning is empty"),
])
def test_guardrail_rejects(raw, reason):
    with pytest.raises(GuardrailRejection, match=reason):
        guardrail_validate(raw)


def test_guardrail_accepts_fenced_json():
    assert guardrail_validate("```json\n" + VALID + "\n```").Severity.value == "High"


def test_repair_loop_recovers_and_is_traced():
    fn = scripted("oops, not JSON", VALID)
    trace, attempts = AgentTrace(), []
    result = generate_triage_report("chest pain", "ctx", completion_fn=fn, trace=trace, attempts_out=attempts)
    assert result.Severity.value == "High"
    assert [a["valid"] for a in attempts] == [False, True]
    # The repair message carries the validation error and the rejected output back to Agent 3.
    repair_messages = fn.calls[1]
    assert repair_messages[2] == {"role": "assistant", "content": "oops, not JSON"}
    assert "not valid JSON" in repair_messages[3]["content"]
    statuses = [(s["agent_no"], s["status"]) for s in trace.as_list()]
    assert statuses == [(3, "ok"), (4, "error"), (3, "repaired"), (4, "repaired")]


def test_repair_loop_fails_safely_after_max_attempts():
    fn = scripted("bad", "bad", "bad", VALID)
    with pytest.raises(LLMGenerationError, match="after 3 attempts"):
        generate_triage_report("x", "ctx", completion_fn=fn, max_repairs=2)
    assert len(fn.calls) == 3


def test_weak_evidence_is_in_prompt_and_caps_confidence():
    fn = scripted(VALID)
    evidence = {"evidence_strength": "weak", "low_evidence": True, "top_similarity": 0.2,
                "mean_similarity": 0.1, "label_agreement": 0.5}
    result = generate_triage_report("x", "ctx", evidence=evidence, completion_fn=fn)
    assert "WEAK" in fn.calls[0][0]["content"]
    assert result.Confidence == "Medium"


def test_structured_context_reaches_the_user_message():
    fn = scripted(VALID)
    generate_triage_report("chest pain", "ctx", completion_fn=fn,
                           structured_context={"vitals": {"heart_rate": 120, "o2sat": 91}, "pain": 8,
                                               "consciousness": "alert", "age": 70, "gender": "M"})
    user = fn.calls[0][1]["content"]
    assert "HR 120" in user and "SpO2 91%" in user and "Pain score (0-10): 8" in user and "Sex: male" in user


def test_prompt_versions_differ():
    v1 = llm_service.build_system_prompt("ctx", None, "v1")
    v2 = llm_service.build_system_prompt("ctx", None, "v2")
    assert "NEVER default" in v1 and "Normal vital signs do NOT make a high-risk" in v2
