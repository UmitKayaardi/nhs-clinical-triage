"""
Pydantic schemas for the triage report.

The field names on TriageResult intentionally match the exact JSON
contract required by the LLM prompt (Symptoms, Duration,
Possible_Conditions, Severity, Reasoning, Required_Actions) so that the
LLM's raw JSON output can be parsed directly into this model with no key
remapping. This model *is* Agent 4 (Medical Guardrail): anything that
does not validate against it is rejected before it reaches a clinician.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.mimic_models import SeverityLevel


class VitalsInput(BaseModel):
    """Optional triage-time vitals for structured intake (feeds Agent 2's vitals similarity)."""

    temperature: Optional[float] = Field(default=None, description="Fahrenheit, as in MIMIC-IV-ED")
    heart_rate: Optional[float] = None
    resp_rate: Optional[float] = None
    o2sat: Optional[float] = None
    sbp: Optional[float] = None
    dbp: Optional[float] = None


class PatientContext(BaseModel):
    """Optional identifiers/demographics. Used only for audit and Agent 7 bias monitoring."""

    patient_id: Optional[str] = Field(default=None, max_length=64)
    age: Optional[int] = Field(default=None, ge=0, le=120)
    gender: Optional[Literal["M", "F"]] = None
    ethnicity: Optional[str] = Field(default=None, max_length=100)


class StructuredIntakeRequest(PatientContext):
    """Body of POST /process-triage/structured: symptom text instead of audio."""

    chief_complaint: str = Field(..., min_length=3, max_length=2000)
    vitals: Optional[VitalsInput] = None


class SimilarCaseSchema(BaseModel):
    """One piece of historical evidence returned to the client for transparency."""

    case_id: Optional[int] = None
    chief_complaint: str
    icd_title: str
    severity: str
    diagnoses: List[str] = Field(default_factory=list)
    vitals: Dict[str, Optional[float]] = Field(default_factory=dict)
    treatments: List[str] = Field(default_factory=list)
    similarity_score: float = 0.0


class TriageResult(BaseModel):
    """
    The structured output the LLM must produce, validated on the way
    out of llm_service.py. Matches the forced JSON schema exactly:
    {"Symptoms": [], "Duration": "", "Possible_Conditions": [],
     "Severity": "High/Medium/Low", "Reasoning": "", "Required_Actions": []}
    """

    Symptoms: List[str] = Field(default_factory=list)
    Duration: str = ""
    Possible_Conditions: List[str] = Field(default_factory=list)
    Severity: SeverityLevel
    Reasoning: str = ""
    Required_Actions: List[str] = Field(default_factory=list)


class AlertDispatchSchema(BaseModel):
    """Outcome of Agent 5 for this request (None when no alert was due)."""

    message_sid: Optional[str] = None
    status: str
    timestamp: str


class TriageReportResponse(BaseModel):
    """Full API response returned by the /process-triage endpoints."""

    transcript: str
    triage_result: TriageResult
    evidence_cases: List[SimilarCaseSchema]
    session_id: Optional[str] = None
    alert: Optional[AlertDispatchSchema] = None
