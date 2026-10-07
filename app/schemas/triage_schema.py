"""
Pydantic schemas for the triage report.

The field names on TriageResult intentionally match the exact JSON
contract required by the LLM prompt (Symptoms, Duration,
Possible_Conditions, Severity) so that the LLM's raw JSON output can be
parsed directly into this model with no key remapping.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.mimic_models import SeverityLevel


class SimilarCaseSchema(BaseModel):
    """One piece of historical evidence returned to the client for transparency."""

    chief_complaint: str
    icd_title: str
    severity: str


class TriageResult(BaseModel):
    """
    The structured output the LLM must produce, validated on the way
    out of llm_service.py. Matches the forced JSON schema exactly:
    {"Symptoms": [], "Duration": "", "Possible_Conditions": [], "Severity": "High/Medium/Low"}
    """

    Symptoms: List[str] = Field(default_factory=list)
    Duration: str = ""
    Possible_Conditions: List[str] = Field(default_factory=list)
    Severity: SeverityLevel


class TriageReportResponse(BaseModel):
    """Full API response returned by POST /process-triage."""

    transcript: str
    triage_result: TriageResult
    evidence_cases: List[SimilarCaseSchema]
    session_id: Optional[str] = None
