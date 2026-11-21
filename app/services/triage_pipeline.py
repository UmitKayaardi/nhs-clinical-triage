"""
The clinical core of the workflow -- Agents 2, 3 and 4 -- as one function
shared by the live API (app/api/v1/triage_routes.py) and the offline
evaluation (evaluation/llm_runner.py), so the evaluated system is exactly
the deployed one.

  Agent 2  Evidence Retrieval    top-k similar historical cases + evidence strength (WP2)
  Agent 3  Clinical Reasoning    LLM draft, grounded in Agent 2's evidence
  Agent 4  Medical Guardrail     schema validation + repair loop (WP3.1)
                                 + NEWS2 clinical safety net (WP3.2): may raise, never lower, severity
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.core.config import get_settings
from app.models.mimic_models import SeverityLevel
from app.schemas.triage_schema import TriageResult
from app.services import llm_service, retrieval_service
from app.services.news2 import apply_safety_net, calculate_news2
from app.services.trace import AgentTrace

VITAL_FIELDS = ("temperature", "heart_rate", "resp_rate", "o2sat", "sbp", "dbp")


@dataclass
class TriageInput:
    complaint: str
    vitals: Dict[str, Optional[float]] = field(default_factory=dict)
    pain: Optional[float] = None
    consciousness: Optional[str] = None
    age: Optional[float] = None
    gender: Optional[str] = None
    arrival_mode: Optional[str] = None
    injury: Optional[bool] = None

    def structured_context(self) -> Optional[Dict]:
        ctx = {"vitals": {k: v for k, v in (self.vitals or {}).items() if v is not None and k in VITAL_FIELDS},
               "pain": self.pain, "consciousness": self.consciousness, "age": self.age, "gender": self.gender,
               "arrival_mode": self.arrival_mode, "injury": self.injury}
        has_data = ctx["vitals"] or any(ctx[k] is not None for k in ctx if k != "vitals")
        return ctx if has_data else None


@dataclass
class ClinicalOutcome:
    triage_result: TriageResult          # final, after the safety net (Severity may be raised)
    llm_severity: str                    # Agent 3's validated severity before the safety net
    similar_cases: List[retrieval_service.SimilarCase]
    evidence: Dict
    news2: Dict
    safety: Dict
    attempts: List[Dict]
    timings_ms: Dict[str, float]


def run_clinical_agents(
    db,
    data: TriageInput,
    trace: Optional[AgentTrace] = None,
    retrieve_kwargs: Optional[Dict] = None,
    completion_fn: Optional[Callable] = None,
    news2_enabled: Optional[bool] = None,
    prompt_version: Optional[str] = None,
) -> ClinicalOutcome:
    """
    Runs Agents 2 -> 3 -> 4 for one patient.

    Args:
        db: SQLAlchemy session (unused when retrieve_kwargs supplies an `index`).
        retrieve_kwargs: extra arguments for find_similar_cases (evaluation passes a
            training-only `index` so a test case never retrieves itself).
        completion_fn: LLM call override (evaluation uses a cached one).
        news2_enabled: defaults to settings.NEWS2_SAFETY_NET_ENABLED.

    Raises:
        llm_service.LLMGenerationError when no draft passes the guardrail.
    """
    settings = get_settings()
    trace = trace if trace is not None else AgentTrace()
    news2_enabled = settings.NEWS2_SAFETY_NET_ENABLED if news2_enabled is None else news2_enabled
    vitals = {k: v for k, v in (data.vitals or {}).items() if v is not None}
    timings: Dict[str, float] = {}

    # --- Agent 2: evidence retrieval + evidence strength ---
    with trace.step(2, input={"query_text": data.complaint, "vitals": vitals or None},
                    messages_to=["Agent 3"]) as step:
        t0 = time.perf_counter()
        cases = retrieval_service.find_similar_cases(db, data.complaint, vitals or None, **(retrieve_kwargs or {}))
        evidence = retrieval_service.assess_evidence(cases)
        db_context = retrieval_service.format_cases_as_context(cases)
        timings["agent2_retrieval"] = (time.perf_counter() - t0) * 1000
        step["output"] = {
            "cases": [{"stay_id": c.stay_id, "chief_complaint": c.chief_complaint, "severity": c.severity,
                       "similarity": c.similarity_score} for c in cases],
            **evidence,
        }
        step["summary"] = (f"{len(cases)} cases, top similarity {evidence['top_similarity']:.2f}, "
                           f"evidence {evidence['evidence_strength']}")

    # --- Agents 3 + 4: reasoning with guardrail validation and repair loop ---
    attempts: List[Dict] = []
    t0 = time.perf_counter()
    result = llm_service.generate_triage_report(
        data.complaint, db_context,
        evidence=evidence, structured_context=data.structured_context(),
        completion_fn=completion_fn, trace=trace, attempts_out=attempts,
        **({"prompt_version": prompt_version} if prompt_version else {}),
    )
    timings["agent3_4_wall"] = (time.perf_counter() - t0) * 1000
    # Agent 3 = API latency reported by the completion (the original latency for cached calls);
    # Agent 4 = guardrail validation time measured directly for every attempt (never derived by subtraction).
    timings["agent3_llm"] = sum((a.get("latency_ms") or 0.0) for a in attempts)
    timings["agent4_guardrail"] = sum((a.get("guardrail_ms") or 0.0) for a in attempts)
    llm_severity = result.Severity.value

    # --- Agent 4: NEWS2 clinical safety net (raise-only) ---
    with trace.step(4, input={"llm_severity": llm_severity, "vitals": vitals or None,
                              "consciousness": data.consciousness},
                    messages_to=["Persistence", "Agent 5"], agent_name="Medical Guardrail (NEWS2 safety net)") as step:
        t0 = time.perf_counter()
        news2 = calculate_news2(vitals, data.consciousness)
        if news2_enabled:
            safety = apply_safety_net(llm_severity, news2)
        else:
            safety = {"severity": llm_severity, "safety_override": False, "override_reason": None,
                      "news2_score": news2.score}
        if safety["safety_override"]:
            result = result.model_copy(update={"Severity": SeverityLevel(safety["severity"])})
            step["status"] = "overridden"
        timings["agent4_news2"] = (time.perf_counter() - t0) * 1000
        step["output"] = {"news2": news2.as_dict(), "final_severity": safety["severity"],
                          "safety_override": safety["safety_override"], "override_reason": safety["override_reason"],
                          "enabled": news2_enabled}
        step["summary"] = (f"NEWS2 {news2.score if news2.score is not None else 'n/a'}, final severity "
                           f"{safety['severity']}" + (" (raised)" if safety["safety_override"] else ""))

    return ClinicalOutcome(
        triage_result=result,
        llm_severity=llm_severity,
        similar_cases=cases,
        evidence=evidence,
        news2=news2.as_dict(),
        safety=safety,
        attempts=attempts,
        timings_ms={k: round(v, 3) for k, v in timings.items()},
    )
