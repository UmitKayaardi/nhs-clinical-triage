"""Every agent duration must be >= 0, also when Agent 3's latency comes from the LLM cache."""

import json

import pandas as pd

from app.services import retrieval_service
from app.services.trace import AgentTrace
from app.services.triage_pipeline import TriageInput, run_clinical_agents
from evaluation.llm_runner import LLMJob, run_job

VALID = json.dumps({"Symptoms": ["chest pain"], "Duration": "1 hour", "Possible_Conditions": ["ACS"],
                    "Severity": "Low", "Confidence": "Medium", "Reasoning": "Minor.", "Required_Actions": []})


def cached_like(messages, params):
    # A cache hit returns instantly but reports the ORIGINAL API latency (here 1.5 s).
    return VALID, {"latency_ms": 1500.0, "usage": {"total_tokens": 100}, "cached": True}


def flaky_then_cached(responses):
    it = iter(responses)
    return lambda messages, params: (next(it), {"latency_ms": 900.0, "usage": {"total_tokens": 80}, "cached": True})


def test_pipeline_timings_and_trace_durations_are_non_negative(db):
    trace = AgentTrace()
    out = run_clinical_agents(db, TriageInput(complaint="chest pain", vitals={"heart_rate": 140, "resp_rate": 30}),
                              trace=trace, completion_fn=cached_like)
    assert all(v >= 0 for v in out.timings_ms.values()), out.timings_ms
    assert out.timings_ms["agent3_llm"] == 1500.0
    assert out.timings_ms["agent4_guardrail"] < 1500.0
    assert all(step["duration_ms"] >= 0 for step in trace.as_list())


def test_repaired_attempts_keep_non_negative_durations(db):
    trace = AgentTrace()
    out = run_clinical_agents(db, TriageInput(complaint="chest pain"), trace=trace,
                              completion_fn=flaky_then_cached(["not json", VALID]))
    assert len(out.attempts) == 2 and all(a["guardrail_ms"] >= 0 for a in out.attempts)
    assert all(v >= 0 for v in out.timings_ms.values())
    assert all(step["duration_ms"] >= 0 for step in trace.as_list())


def test_evaluation_latency_fields_are_non_negative(db):
    index = retrieval_service.build_index(retrieval_service.records_from_db(db))
    cases = pd.DataFrame([{"case_id": "c1", "label": "High", "complaint": "chest pain", "temperature": None,
                           "heart_rate": 120.0, "resp_rate": None, "o2sat": None, "sbp": None, "dbp": None,
                           "pain": None, "consciousness": None, "age": None, "gender": "M",
                           "arrival_mode": None, "injury": None}])
    class Cached:
        api_calls = 0

        def __call__(self, messages, params):
            return cached_like(messages, params)

    res = run_job(LLMJob("t", "mimic", "S4", "mimic-train"), cases, index, Cached(), progress_every=0)
    rec = res["records"][0]
    for key in ("latency_agent2_ms", "latency_agent3_ms", "latency_agent4_ms"):
        assert rec[key] >= 0, (key, rec[key])
