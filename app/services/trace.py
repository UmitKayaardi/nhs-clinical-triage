"""
WP4 -- Agent Trace.

Records what every agent received, did and produced for one triage
session, so each step of the workflow can be shown as evidence
(Doctor Portal "Agent Trace" view, GET /api/v1/sessions/{id}/trace).

Each step: agent_no, agent_name, started_at, duration_ms, input (safe
summary -- never secrets or phone numbers), output (JSON), status
(ok | repaired | overridden | mocked | skipped | error), messages_to (the
agent(s) that receive this output) and a one-line summary that is also
written to the console as:
    [Agent 2 | Evidence Retrieval Agent] 5 cases, top similarity 0.71, 182 ms
    [Agent 4 | Medical Guardrail Agent | NEWS2 safety net] NEWS2 6, final severity High, 0.1 ms

Agent names are exactly those of the submitted workflow (Umit_Kayaardi_3231603_Workflow.pdf). An agent
that runs more than one step (Agent 1 structured intake, Agent 4 schema check / NEWS2 safety net) keeps
its name and labels the step with an optional `stage`.
"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("agent_trace")

AGENT_NAMES = {
    1: "Data Intake & Transcription Agent",
    2: "Evidence Retrieval Agent",
    3: "Clinical Reasoning Agent",
    4: "Medical Guardrail Agent",
    5: "Orchestrator & Action Agent",
    6: "Post-Deployment Monitor Agent",
    7: "Drift Detection & Bias Monitor Agent",
    0: "Persistence",
}


def _label(agent_name: str, stage: Optional[str]) -> str:
    return f"{agent_name} | {stage}" if stage else agent_name

_MAX_TEXT = 600


def _safe(value: Any) -> Any:
    """Makes a value JSON-safe and trims long strings."""
    if isinstance(value, str):
        return value if len(value) <= _MAX_TEXT else value[: _MAX_TEXT - 3] + "..."
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _safe(value.model_dump(mode="json"))
    return str(value)


class AgentTrace:
    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []

    @contextmanager
    def step(self, agent_no: int, input: Any = None, messages_to: Optional[List[str]] = None,
             agent_name: Optional[str] = None, stage: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """
        Usage:
            with trace.step(2, input={...}, messages_to=["Agent 3"]) as s:
                ...
                s["output"] = {...}; s["summary"] = "5 cases, top similarity 0.71"
        The caller may set s["status"]; an exception marks the step "error" and is re-raised.
        """
        entry: Dict[str, Any] = {
            "agent_no": agent_no,
            "agent_name": agent_name or AGENT_NAMES.get(agent_no, f"Agent {agent_no}"),
            "stage": stage,
            "started_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "duration_ms": None,
            "input": _safe(input),
            "output": None,
            "status": "ok",
            "messages_to": messages_to or [],
            "summary": "",
        }
        start = time.perf_counter()
        try:
            yield entry
        except Exception as exc:
            entry["status"] = "error"
            entry["output"] = entry["output"] or {"error": str(exc)[:300]}
            raise
        finally:
            entry["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            entry["output"] = _safe(entry["output"])
            self.steps.append(entry)
            label = f"Agent {agent_no}" if agent_no else "Step"
            logger.info("[%s | %s] %s%s ms (%s)", label, _label(entry["agent_name"], stage),
                        (entry["summary"] + ", ") if entry["summary"] else "", entry["duration_ms"], entry["status"])

    def add(self, agent_no: int, input: Any, output: Any, status: str = "ok", summary: str = "",
            messages_to: Optional[List[str]] = None, duration_ms: float = 0.0,
            agent_name: Optional[str] = None, stage: Optional[str] = None) -> None:
        """Adds an already-finished step (e.g. one Agent 3 attempt timed elsewhere)."""
        self.steps.append({
            "agent_no": agent_no,
            "agent_name": agent_name or AGENT_NAMES.get(agent_no, f"Agent {agent_no}"),
            "stage": stage,
            "started_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "duration_ms": round(duration_ms, 1),
            "input": _safe(input),
            "output": _safe(output),
            "status": status,
            "messages_to": messages_to or [],
            "summary": summary,
        })
        logger.info("[Agent %s | %s] %s%s ms (%s)", agent_no, _label(self.steps[-1]["agent_name"], stage),
                    (summary + ", ") if summary else "", round(duration_ms, 1), status)

    def as_list(self) -> List[Dict[str, Any]]:
        return self.steps

    def to_json(self) -> str:
        return json.dumps(self.steps)
