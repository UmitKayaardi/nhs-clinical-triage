"""
LLM integration service (Groq API).

Generates the structured JSON triage report from a patient transcript
and the historical evidence retrieved by db_service.py.

CRITICAL DOMAIN CONSTRAINT: this service must never let the model invent
a severity level from its own clinical judgment. The system prompt
explicitly instructs the model to derive Severity and Possible_Conditions
only from the injected db_context evidence, and to say so plainly when
the evidence is insufficient, rather than guessing. This code enforces
the contract structurally (forced JSON schema + Pydantic validation) but
the actual grounding behaviour still depends on the prompt and the
underlying model -- treat this as a decision-support draft for clinical
review, not an autonomous diagnostic system.
"""

import json
import logging
import re

from groq import Groq
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.triage_schema import TriageResult

logger = logging.getLogger(__name__)
settings = get_settings()

_client: Groq | None = None


def _get_client() -> Groq:
    """Lazily instantiates the Groq client as a module-level singleton."""
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


class LLMGenerationError(Exception):
    """Raised when the LLM call fails or its output cannot be parsed/validated."""


_SYSTEM_PROMPT_TEMPLATE = """You are a clinical triage support assistant used by an NHS Emergency \
Department. You are NOT a doctor and you must NOT perform independent clinical diagnosis.

Your only job is to structure the patient's reported symptoms and to determine severity \
STRICTLY by comparing the patient's complaint to the historical evidence provided below. \
Do not use outside medical knowledge to override or guess a severity that is not supported \
by the evidence. If the evidence is weak, contradictory, or absent, say so honestly in the \
output rather than inventing a confident answer.

Historical evidence (past similar cases from the hospital database):
{db_context}

Rules:
1. Base "Possible_Conditions" only on the diagnoses shown in the evidence above. If no \
   evidence is available, return an empty list rather than guessing a condition.
2. Base "Severity" only on the "Recorded Severity" values shown in the evidence above \
   (High, Medium, or Low). If the evidence is empty or contains no severity signal, set \
   Severity to "Medium" and note the uncertainty in a Possible_Conditions entry such as \
   "Insufficient historical evidence - clinician review required". Never fabricate a High \
   or Low severity without supporting evidence.
3. Extract "Symptoms" and "Duration" directly from what the patient said, not from the \
   historical evidence.
4. Respond with ONLY a single JSON object, no prose, no markdown code fences, no explanation.

Required JSON schema (respond in exactly this shape):
{{"Symptoms": ["..."], "Duration": "...", "Possible_Conditions": ["..."], "Severity": "High|Medium|Low"}}
"""

_MARKDOWN_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_markdown_fences(raw: str) -> str:
    """
    Removes ```json / ``` fences that models sometimes wrap around JSON
    output despite instructions not to, so json.loads() doesn't choke on them.
    """
    return _MARKDOWN_FENCE_RE.sub("", raw).strip()


def generate_triage_report(transcript: str, db_context: str) -> TriageResult:
    """
    Calls the Groq API to generate a structured triage report.

    Args:
        transcript: The patient's transcribed speech.
        db_context: Formatted historical evidence string from db_service.py
            (see db_service.format_cases_as_context).

    Returns:
        A validated TriageResult.

    Raises:
        LLMGenerationError: on API failure, non-JSON output, or output
            that fails schema validation.
    """
    client = _get_client()
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(db_context=db_context)

    try:
        completion = client.chat.completions.create(
            # CRITICAL: must remain openai/gpt-oss-20b per project requirements.
            model=settings.GROQ_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Patient statement: \"{transcript}\""},
            ],
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            # Ask the API to enforce JSON output where supported. Even if
            # the model ignores this, _strip_markdown_fences() below is
            # the real safety net for parsing.
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.exception("Groq API call failed")
        raise LLMGenerationError(f"LLM request failed: {exc}") from exc

    raw_content = completion.choices[0].message.content if completion.choices else None
    if not raw_content:
        raise LLMGenerationError("LLM returned an empty response.")

    cleaned = _strip_markdown_fences(raw_content)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM output as JSON. Raw output: %s", raw_content)
        raise LLMGenerationError(f"LLM output was not valid JSON: {exc}") from exc

    try:
        return TriageResult(**parsed)
    except ValidationError as exc:
        logger.error("LLM output failed schema validation. Parsed: %s", parsed)
        raise LLMGenerationError(f"LLM output did not match the required schema: {exc}") from exc
