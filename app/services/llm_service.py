"""
Agents 3 and 4 -- Clinical Reasoning (Groq LLM) and the Medical Guardrail
repair loop.

Agent 3 turns the patient statement, any structured intake data (vitals,
pain, consciousness, age, sex) and Agent 2's historical evidence into the
structured JSON triage report. Agent 4 validates every draft:
  - output must be a JSON object (markdown fences are stripped first),
  - it must validate against the TriageResult schema (Pydantic),
  - Severity must be present and one of High/Medium/Low,
  - Reasoning must not be empty.
When a draft is rejected, Agent 4 sends the validation error and the
rejected output back to Agent 3 with a repair instruction (up to
LLM_MAX_REPAIR_ATTEMPTS times). If every attempt fails, the request fails
safely (LLMGenerationError -> HTTP 502) and nothing is shown to a clinician.

When Agent 2 reports weak evidence, the prompt says so and the model must
state lower confidence. Every attempt is recorded in the agent trace.

This is a decision-support draft for clinical review, not an autonomous
diagnostic system.
"""

import json
import logging
import re
import time
from typing import Callable, Dict, List, Optional, Tuple

from groq import Groq
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.triage_schema import TriageResult

logger = logging.getLogger(__name__)
settings = get_settings()

_client: Optional[Groq] = None

# completion_fn(messages, params) -> (raw_text, meta). meta may hold usage, latency_ms, cached.
CompletionFn = Callable[[List[Dict[str, str]], Dict], Tuple[str, Dict]]


def _get_client() -> Groq:
    """Lazily instantiates the Groq client as a module-level singleton."""
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


class LLMGenerationError(Exception):
    """Raised when the LLM call fails or no attempt passes the guardrail."""


class GuardrailRejection(Exception):
    """Agent 4 rejected one draft from Agent 3."""


_SYSTEM_PROMPT_TEMPLATE = """You are a clinical triage support assistant used by an NHS Emergency \
Department.

Your job is to structure the patient's reported symptoms and evaluate the severity based PRIMARILY \
on the patient's actual presentation (statement plus any recorded vital signs). Use the historical \
evidence provided below only as a helpful reference. Do NOT blindly copy the severity or diagnoses \
from past cases if the current patient's situation is clearly different.

Triage levels:
- High: needs immediate or very urgent assessment (life, limb or organ threat; abnormal vital signs \
such as SpO2 below 92%, systolic BP below 90, heart rate above 130, respiratory rate above 24, \
reduced consciousness; severe pain with red flags).
- Medium: urgent but stable; needs several investigations or treatments.
- Low: less urgent or non-urgent; stable, minor problem, at most one simple intervention.

Historical evidence (past similar cases from the hospital database):
{db_context}

Evidence strength: {evidence_line}

Rules:
1. Extract "Symptoms" and "Duration" directly from what the patient said.
2. Determine "Severity" (High, Medium, or Low) from the patient's actual condition and vital signs:
   - If the patient reports mild symptoms and has no red flags, assign "Low".
   - NEVER default to "Medium" or "High" just because past database cases were severe or missing.
3. Base "Possible_Conditions" on the historical evidence, but if the patient has a clear minor \
illness, you can suggest general conditions (e.g., "Common Cold", "Mild Tension Headache").
4. In "Reasoning", explain in one to three sentences why you chose this severity, naming the red \
flags (or their absence) and which historical cases, if any, informed the decision.{weak_rule}
5. "Confidence" is your confidence in the severity: High, Medium or Low.
6. In "Required_Actions", list the immediate next steps for the triage nurse (e.g. "ECG within \
10 minutes", "Re-check vitals in 30 minutes"). These are suggestions for clinician review only.
7. Respond with ONLY a single JSON object, no prose, no markdown code fences, no explanation.

Required JSON schema (respond in exactly this shape):
{{"Symptoms": ["..."], "Duration": "...", "Possible_Conditions": ["..."], "Severity": "High|Medium|Low", \
"Confidence": "High|Medium|Low", "Reasoning": "...", "Required_Actions": ["..."]}}
"""

# v2 (default): triage levels follow the ESI / KTAS acuity definitions that the 3-tier labels come
# from (1-2 High, 3 Medium, 4-5 Low). v1 (above) is kept for the prompt ablation: it told the model to
# assign Low whenever vital signs were normal, which under-triaged high-risk complaints.
_SYSTEM_PROMPT_V2 = """You are a clinical triage support assistant used by an NHS Emergency \
Department. You assign a 3-tier triage priority that maps onto the Emergency Severity Index / \
Korean Triage and Acuity Scale (levels 1-2 = High, 3 = Medium, 4-5 = Low).

Triage levels (decide in this order):
- High: (a) needs immediate life-saving intervention, OR (b) a HIGH-RISK presentation that should \
not wait, even when vital signs are currently normal -- e.g. chest pain that could be cardiac, \
suspected aortic dissection, stroke or new neurological deficit, significant bleeding (GI \
bleeding, haematemesis, rectal bleeding with risk factors), shortness of breath with any \
abnormal finding, new confusion or altered consciousness, suspected sepsis, severe allergic \
reaction, overdose or suicidal intent, major trauma, severe pain (7-10/10) or distress, OR \
(c) danger-zone vital signs (SpO2 < 92%, systolic BP < 90, heart rate > 130 or < 40, \
respiratory rate > 24, temperature > 39.5 C / 103 F with tachycardia).
- Medium: stable and not high-risk, but likely to need TWO OR MORE resources (blood tests, \
imaging, IV fluids or IV/IM medication, specialist consultation, procedural sedation) -- e.g. \
abdominal pain, vomiting with dehydration, fracture needing reduction, fever with abnormal \
tests, moderate pain.
- Low: stable, low-risk, likely to need ONE resource or none -- e.g. simple laceration, sprain, \
minor injury, rash, sore throat, medication refill, minor burn, mild pain.

Historical evidence (past similar cases from the hospital database):
{db_context}

Evidence strength: {evidence_line}

Rules:
1. Extract "Symptoms" and "Duration" directly from what the patient said.
2. Determine "Severity" with the definitions above. Normal vital signs do NOT make a high-risk \
complaint low-risk. Use the historical cases as supporting evidence of how similar patients \
were triaged, but do not copy them if the current presentation clearly differs.
3. If you are uncertain between two levels, choose the MORE urgent one (under-triage is more \
harmful than over-triage); say so in Reasoning.
4. Base "Possible_Conditions" on the presentation and the historical evidence.
5. In "Reasoning", explain in one to three sentences why you chose this severity, naming the \
high-risk features or danger-zone vital signs (or their absence), the expected resources, and \
which historical cases, if any, informed the decision.{weak_rule}
6. "Confidence" is your confidence in the severity: High, Medium or Low.
7. In "Required_Actions", list the immediate next steps for the triage nurse (e.g. "ECG within \
10 minutes", "Re-check vitals in 30 minutes"). These are suggestions for clinician review only.
8. Respond with ONLY a single JSON object, no prose, no markdown code fences, no explanation.

Required JSON schema (respond in exactly this shape):
{{"Symptoms": ["..."], "Duration": "...", "Possible_Conditions": ["..."], "Severity": "High|Medium|Low", \
"Confidence": "High|Medium|Low", "Reasoning": "...", "Required_Actions": ["..."]}}
"""

PROMPTS = {"v1": _SYSTEM_PROMPT_TEMPLATE, "v2": _SYSTEM_PROMPT_V2}

_WEAK_RULE = (" The historical evidence for this patient is WEAK: say so in Reasoning, rely on the "
              "presentation and vital signs, and do not give High confidence.")

_REPAIR_TEMPLATE = (
    "The Medical Guardrail rejected your previous output.\n"
    "Validation error: {error}\n"
    "Return ONLY one corrected JSON object with exactly the keys Symptoms, Duration, "
    "Possible_Conditions, Severity (High|Medium|Low), Confidence (High|Medium|Low), Reasoning "
    "(non-empty) and Required_Actions. No prose, no code fences."
)

_MARKDOWN_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_markdown_fences(raw: str) -> str:
    """Removes ```json / ``` fences that models sometimes wrap around JSON output."""
    return _MARKDOWN_FENCE_RE.sub("", raw).strip()


def _evidence_line(evidence: Optional[Dict]) -> str:
    if not evidence:
        return "not assessed"
    return (f"{evidence['evidence_strength'].upper()} (top similarity {evidence['top_similarity']:.2f}, "
            f"mean {evidence['mean_similarity']:.2f}, label agreement {evidence['label_agreement']:.0%})")


def build_system_prompt(db_context: str, evidence: Optional[Dict] = None, prompt_version: Optional[str] = None) -> str:
    weak = bool(evidence and evidence.get("low_evidence"))
    template = PROMPTS[prompt_version or settings.LLM_PROMPT_VERSION]
    return template.format(db_context=db_context, evidence_line=_evidence_line(evidence),
                                          weak_rule=_WEAK_RULE if weak else "")


def format_structured_context(context: Optional[Dict]) -> str:
    """Formats structured intake data (vitals, pain, AVPU, demographics) for the user message."""
    if not context:
        return ""
    lines = []
    if context.get("age") is not None:
        lines.append(f"- Age: {context['age']:g}")
    if context.get("gender"):
        lines.append(f"- Sex: {'male' if context['gender'] == 'M' else 'female' if context['gender'] == 'F' else context['gender']}")
    v = context.get("vitals") or {}
    parts = []
    if v.get("temperature") is not None:
        parts.append(f"Temp {v['temperature']:.1f} F")
    if v.get("heart_rate") is not None:
        parts.append(f"HR {v['heart_rate']:g}")
    if v.get("resp_rate") is not None:
        parts.append(f"RR {v['resp_rate']:g}")
    if v.get("o2sat") is not None:
        parts.append(f"SpO2 {v['o2sat']:g}%")
    if v.get("sbp") is not None:
        parts.append(f"BP {v['sbp']:g}/{v['dbp']:g}" if v.get("dbp") is not None else f"SBP {v['sbp']:g}")
    if parts:
        lines.append("- Vital signs: " + ", ".join(parts))
    if context.get("pain") is not None:
        lines.append(f"- Pain score (0-10): {context['pain']:g}")
    if context.get("consciousness"):
        lines.append(f"- Consciousness (AVPU): {context['consciousness']}")
    if context.get("arrival_mode"):
        lines.append(f"- Arrival mode: {context['arrival_mode']}")
    if context.get("injury") is not None:
        lines.append(f"- Injury-related presentation: {'yes' if context['injury'] else 'no'}")
    return ("\nStructured intake data:\n" + "\n".join(lines)) if lines else ""


def build_messages(transcript: str, db_context: str, evidence: Optional[Dict] = None,
                   structured_context: Optional[Dict] = None, prompt_version: Optional[str] = None) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": build_system_prompt(db_context, evidence, prompt_version)},
        {"role": "user", "content": f"Patient statement: \"{transcript}\"" + format_structured_context(structured_context)},
    ]


def llm_params() -> Dict:
    params = {
        "model": settings.GROQ_MODEL_NAME,   # must remain openai/gpt-oss-20b per project requirements
        "temperature": settings.LLM_TEMPERATURE,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if settings.LLM_REASONING_EFFORT:
        params["reasoning_effort"] = settings.LLM_REASONING_EFFORT
    return params


def groq_completion(messages: List[Dict[str, str]], params: Dict) -> Tuple[str, Dict]:
    """Default completion function: one Groq chat completion."""
    kwargs = {k: v for k, v in params.items() if k != "reasoning_effort"}
    if "reasoning_effort" in params:
        # groq SDK 0.13 has no reasoning_effort argument; the API accepts it in the body.
        kwargs["extra_body"] = {"reasoning_effort": params["reasoning_effort"]}
    start = time.perf_counter()
    try:
        completion = _get_client().chat.completions.create(messages=messages, **kwargs)
    except Exception as exc:
        logger.exception("Groq API call failed")
        raise LLMGenerationError(f"LLM request failed: {exc}") from exc
    content = completion.choices[0].message.content if completion.choices else None
    usage = getattr(completion, "usage", None)
    meta = {
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        "usage": {"prompt_tokens": getattr(usage, "prompt_tokens", None),
                  "completion_tokens": getattr(usage, "completion_tokens", None),
                  "total_tokens": getattr(usage, "total_tokens", None)} if usage else None,
        "cached": False,
    }
    return content or "", meta


def guardrail_validate(raw_content: str) -> TriageResult:
    """Agent 4 checks on one draft. Raises GuardrailRejection with a precise reason."""
    if not raw_content or not raw_content.strip():
        raise GuardrailRejection("empty response")
    cleaned = _strip_markdown_fences(raw_content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GuardrailRejection(f"output is not valid JSON ({exc.msg} at char {exc.pos})")
    if not isinstance(parsed, dict):
        raise GuardrailRejection("output must be a single JSON object")
    if "Severity" not in parsed or parsed.get("Severity") in (None, ""):
        raise GuardrailRejection("Severity is missing")
    try:
        result = TriageResult(**parsed)
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        raise GuardrailRejection(f"schema validation failed: {errors}")
    if not result.Reasoning.strip():
        raise GuardrailRejection("Reasoning is empty")
    return result


def generate_triage_report(
    transcript: str,
    db_context: str,
    evidence: Optional[Dict] = None,
    structured_context: Optional[Dict] = None,
    completion_fn: Optional[CompletionFn] = None,
    trace=None,
    attempts_out: Optional[List[Dict]] = None,
    max_repairs: Optional[int] = None,
    prompt_version: Optional[str] = None,
) -> TriageResult:
    """
    Agent 3 drafts the report; Agent 4 validates it and, on rejection, asks
    Agent 3 to repair it (max LLM_MAX_REPAIR_ATTEMPTS repairs).

    Args:
        transcript: patient statement (transcribed audio or typed complaint).
        db_context: Agent 2's formatted evidence (retrieval_service.format_cases_as_context).
        evidence: Agent 2's evidence assessment (retrieval_service.assess_evidence).
        structured_context: optional {vitals, pain, consciousness, age, gender, arrival_mode, injury}.
        completion_fn: override for the Groq call (offline evaluation uses a cached one).
        trace: optional AgentTrace; every attempt and every guardrail decision is recorded.
        attempts_out: optional list that receives one dict per attempt (for evaluation stats).

    Raises:
        LLMGenerationError: API failure, or every attempt rejected by the guardrail.
    """
    completion_fn = groq_completion if completion_fn is None else completion_fn
    max_repairs = settings.LLM_MAX_REPAIR_ATTEMPTS if max_repairs is None else max_repairs
    messages = build_messages(transcript, db_context, evidence, structured_context, prompt_version)
    params = llm_params()
    last_error = None

    for attempt in range(1, max_repairs + 2):
        raw, meta = completion_fn(messages, params)
        record = {"attempt": attempt, "latency_ms": meta.get("latency_ms"), "usage": meta.get("usage"),
                  "cached": meta.get("cached", False)}
        if trace is not None:
            trace.add(3, input={"attempt": attempt, "repair": attempt > 1,
                                "user_message": messages[1]["content"],
                                "evidence_strength": (evidence or {}).get("evidence_strength"),
                                **({"repair_instruction": messages[-1]["content"]} if attempt > 1 else {})},
                      output={"raw_output": raw},
                      status="repaired" if attempt > 1 else "ok",
                      summary=f"attempt {attempt}, {(meta.get('usage') or {}).get('total_tokens') or '?'} tokens",
                      messages_to=["Agent 4"], duration_ms=meta.get("latency_ms") or 0.0)
        g_start = time.perf_counter()
        try:
            result = guardrail_validate(raw)
        except GuardrailRejection as exc:
            guardrail_ms = (time.perf_counter() - g_start) * 1000
            last_error = str(exc)
            record.update(valid=False, error=last_error, guardrail_ms=round(guardrail_ms, 3))
            if attempts_out is not None:
                attempts_out.append(record)
            logger.warning("Guardrail rejected attempt %d: %s", attempt, last_error)
            if trace is not None:
                retry = attempt <= max_repairs
                trace.add(4, input={"attempt": attempt}, output={"valid": False, "error": last_error,
                                                                 "action": "repair requested" if retry else "fail safely"},
                          status="error", summary=f"rejected attempt {attempt}: {last_error[:80]}",
                          messages_to=["Agent 3"] if retry else [],
                          duration_ms=guardrail_ms)
            messages = messages[:2] + [
                {"role": "assistant", "content": (raw or "")[:4000]},
                {"role": "user", "content": _REPAIR_TEMPLATE.format(error=last_error)},
            ]
            continue

        if evidence and evidence.get("low_evidence") and result.Confidence == "High":
            result.Confidence = "Medium"  # weak evidence caps the stated confidence
            record["confidence_capped"] = True
        guardrail_ms = (time.perf_counter() - g_start) * 1000
        record.update(valid=True, error=None, guardrail_ms=round(guardrail_ms, 3))
        if attempts_out is not None:
            attempts_out.append(record)
        if trace is not None:
            trace.add(4, input={"attempt": attempt},
                      output={"valid": True, "schema": "TriageResult", "severity": result.Severity.value,
                              "confidence": result.Confidence, "confidence_capped": record.get("confidence_capped", False)},
                      status="repaired" if attempt > 1 else "ok",
                      summary=f"schema valid on attempt {attempt}", messages_to=["NEWS2 safety net"],
                      duration_ms=guardrail_ms)
        return result

    raise LLMGenerationError(
        f"LLM output failed the guardrail after {max_repairs + 1} attempts: {last_error}")
