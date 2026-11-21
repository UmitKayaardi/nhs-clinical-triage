"""
Triage API routes.

POST /process-triage (audio) and POST /process-triage/structured (typed
symptoms + optional vitals) share one pipeline:
  1. Agent 1 -- transcribe the audio (audio intake) / accept typed intake.
  2. Agent 2 -- retrieve similar historical cases across all MIMIC tables
     and rate the evidence strength (WP2).
  3. Agent 3 -- generate the triage report with the LLM, grounded in them.
  4. Agent 4 -- validate the report (schema + repair loop) and apply the
     NEWS2 safety net, which may raise but never lower severity (WP3).
  5. Persist a TriageSession record (audit + monitoring by Agents 6/7).
  6. Agent 5 -- alert for alerting severities: n8n webhook first, direct
     Twilio WhatsApp as fallback, "mocked" in test mode (WP5).
Every step is recorded in an agent trace (WP4), returned in the response,
stored on the session and served by GET /sessions/{id}/trace.
The temp audio file is always cleaned up, even on failure.

Blocking work (Whisper, the Groq call, Twilio retries) runs in the
threadpool so one slow request doesn't stall the event loop.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from functools import lru_cache
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.mimic_models import SeverityLevel, TriageSession
from app.models.monitoring_models import TriageSessionFeedback
from app.schemas.triage_schema import (
    AlertDispatchSchema,
    PatientContext,
    SimilarCaseSchema,
    StructuredIntakeRequest,
    TriageReportResponse,
    VitalsInput,
)
from app.services import audio_service
from app.services.alert_service import log_alert
from app.services.audio_service import TranscriptionError
from app.services.llm_service import LLMGenerationError
from app.services.n8n_service import N8nOrchestrator, N8nUnavailable
from app.services.trace import AgentTrace
from app.services.triage_pipeline import VITAL_FIELDS, TriageInput, run_clinical_agents
from app.services.twilio_service import TwilioService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["Triage"])

_ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}


@lru_cache
def get_twilio_service() -> TwilioService:
    """FastAPI dependency; overridden in tests with a mocked client."""
    return TwilioService()


def get_n8n_orchestrator() -> N8nOrchestrator:
    """FastAPI dependency; built per request so settings changes are picked up (tests override it)."""
    return N8nOrchestrator()


def dispatch_alert(twilio: TwilioService, n8n: N8nOrchestrator, db: Session, trace: AgentTrace,
                   session_id: str, severity: str, chief_complaint: str, reasoning: str,
                   news2_score: Optional[int], low_evidence: Optional[bool], created_at: str,
                   patient_id: Optional[str]) -> Optional[AlertDispatchSchema]:
    """
    Agent 5 -- Orchestrator & Action. Alerting severity -> n8n webhook (when
    configured) -> on failure, direct Twilio WhatsApp -> "mocked" in test mode.
    """
    with trace.step(5, input={"severity": severity, "alert_on": settings.ALERT_ON_SEVERITIES,
                              "n8n_configured": n8n.configured},
                    messages_to=["On-call clinician (WhatsApp)"]) as step:
        if not twilio.should_alert(severity):
            step["status"] = "skipped"
            step["output"] = {"alert": False, "reason": f"severity {severity} not in alert list"}
            step["summary"] = f"no alert for {severity}"
            return None

        body = TwilioService.format_message(severity, chief_complaint, session_id, patient_id, reasoning)
        if n8n.configured:
            event = {"session_id": session_id, "severity": severity, "chief_complaint": chief_complaint[:300],
                     "reasoning": (reasoning or "")[:500], "news2_score": news2_score,
                     "low_evidence": low_evidence, "created_at": created_at, "message": body,
                     "test_mode": bool(twilio.settings.TWILIO_TEST_MODE)}
            try:
                outcome = n8n.send(event)
                log_alert(db, "whatsapp_triage", "critical", body, session_id=session_id,
                          status=outcome["status"], external_id=outcome.get("message_sid"), channel="n8n")
                result = AlertDispatchSchema(message_sid=outcome.get("message_sid"), status=outcome["status"],
                                             timestamp=datetime.utcnow().isoformat(), channel="n8n")
                step["output"] = {"channel": "n8n", "status": result.status, "message_sid": result.message_sid}
                step["summary"] = f"n8n webhook -> {result.status}"
                step["status"] = "mocked" if result.status == "mocked" else "ok"
                return result
            except N8nUnavailable as exc:
                logger.warning("n8n unavailable (%s); falling back to direct Twilio", exc)
                step["input"]["n8n_error"] = str(exc)[:200]

        outcome = twilio.send_whatsapp_alert(patient_id, severity, reasoning, chief_complaint, session_id, db)
        result = AlertDispatchSchema(**outcome)
        step["output"] = {"channel": result.channel, "status": result.status, "message_sid": result.message_sid,
                          "fallback_from_n8n": n8n.configured}
        step["summary"] = f"{result.channel} -> {result.status}"
        step["status"] = "mocked" if result.status == "mocked" else ("error" if result.status == "failed" else "ok")
        return result


async def _run_pipeline(
    db: Session,
    twilio: TwilioService,
    transcript: str,
    intake_mode: str,
    patient: PatientContext,
    vitals: Optional[VitalsInput] = None,
    trace: Optional[AgentTrace] = None,
    arrival_mode: Optional[str] = None,
    injury: Optional[bool] = None,
    n8n: Optional[N8nOrchestrator] = None,
) -> TriageReportResponse:
    trace = trace if trace is not None else AgentTrace()
    n8n = n8n or get_n8n_orchestrator()
    data = TriageInput(
        complaint=transcript,
        vitals=vitals.model_dump(include=set(VITAL_FIELDS)) if vitals else {},
        pain=vitals.pain if vitals else None,
        consciousness=vitals.consciousness if vitals else None,
        age=patient.age,
        gender=patient.gender,
        arrival_mode=arrival_mode,
        injury=injury,
    )

    # --- Agents 2 -> 3 -> 4 (retrieval, reasoning + guardrail repair loop, NEWS2 safety net) ---
    try:
        outcome = await run_in_threadpool(run_clinical_agents, db, data, trace)
    except LLMGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    triage_result = outcome.triage_result
    similar_cases = outcome.similar_cases

    # --- Persist an audit record of this session ---
    with trace.step(0, input={"table": "triage_sessions"}, messages_to=["Agent 5", "Agent 6", "Agent 7"]) as step:
        session_record = TriageSession(
            transcript=transcript,
            chief_complaint=transcript,
            intake_mode=intake_mode,
            llm_raw_response=triage_result.model_dump_json(),
            symptoms=json.dumps(triage_result.Symptoms),
            duration=triage_result.Duration,
            possible_conditions=json.dumps(triage_result.Possible_Conditions),
            severity=triage_result.Severity,
            reasoning=triage_result.Reasoning,
            required_actions=json.dumps(triage_result.Required_Actions),
            evidence_stay_ids=json.dumps([case.stay_id for case in similar_cases]),
            evidence_scores=json.dumps([case.similarity_score for case in similar_cases]),
            patient_id=patient.patient_id,
            age=patient.age,
            gender=patient.gender,
            ethnicity=patient.ethnicity,
            llm_severity=outcome.llm_severity,
            news2_score=outcome.safety["news2_score"],
            safety_override=outcome.safety["safety_override"],
            override_reason=outcome.safety["override_reason"],
            evidence_strength=outcome.evidence["evidence_strength"],
            low_evidence=outcome.evidence["low_evidence"],
            top_similarity=outcome.evidence["top_similarity"],
            vitals_json=json.dumps(vitals.model_dump(exclude_none=True)) if vitals else None,
        )
        db.add(session_record)
        db.commit()
        db.refresh(session_record)
        session_id = str(session_record.id)
        step["output"] = {"session_id": session_id, "severity": triage_result.Severity.value}
        step["summary"] = f"session {session_id[:8]} saved"

    # --- Agent 5: orchestration (n8n -> Twilio fallback) for alerting severities ---
    alert = await run_in_threadpool(
        dispatch_alert, twilio, n8n, db, trace, session_id, triage_result.Severity.value, transcript,
        triage_result.Reasoning, outcome.safety["news2_score"], outcome.evidence["low_evidence"],
        session_record.created_at.isoformat(), patient.patient_id,
    )

    session_record.agent_trace = trace.to_json()
    db.commit()

    return TriageReportResponse(
        transcript=transcript,
        triage_result=triage_result,
        evidence_cases=[
            SimilarCaseSchema(
                case_id=case.stay_id,
                chief_complaint=case.chief_complaint,
                icd_title=case.icd_title,
                severity=case.severity,
                diagnoses=case.diagnoses,
                vitals=case.vitals,
                treatments=case.treatments,
                similarity_score=case.similarity_score,
            )
            for case in similar_cases
        ],
        session_id=session_id,
        alert=alert,
        evidence_strength=outcome.evidence["evidence_strength"],
        low_evidence=outcome.evidence["low_evidence"],
        top_similarity=outcome.evidence["top_similarity"],
        llm_severity=outcome.llm_severity,
        news2_score=outcome.safety["news2_score"],
        news2_components=outcome.news2.get("components") or None,
        safety_override=outcome.safety["safety_override"],
        override_reason=outcome.safety["override_reason"],
        guardrail_attempts=len(outcome.attempts),
        trace=trace.as_list(),
    )


@router.post(
    "/process-triage",
    response_model=TriageReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe patient audio and generate an evidence-grounded triage report",
)
async def process_triage(
    file: UploadFile = File(..., description="Patient audio recording"),
    patient_id: Optional[str] = Form(default=None),
    age: Optional[int] = Form(default=None),
    gender: Optional[str] = Form(default=None),
    ethnicity: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    twilio: TwilioService = Depends(get_twilio_service),
    n8n: N8nOrchestrator = Depends(get_n8n_orchestrator),
) -> TriageReportResponse:
    """
    Full triage pipeline endpoint for audio intake.

    Accepts a single audio file upload plus optional patient context
    (used only for audit and bias monitoring), runs it through
    transcription, evidence retrieval and LLM structuring, and returns
    the resulting report.
    """
    try:
        patient = PatientContext(patient_id=patient_id or None, age=age, gender=gender or None,
                                 ethnicity=ethnicity or None)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors())

    original_ext = os.path.splitext(file.filename or "")[1].lower()
    if original_ext not in _ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format '{original_ext}'. "
            f"Allowed: {sorted(_ALLOWED_AUDIO_EXTENSIONS)}",
        )

    os.makedirs(settings.AUDIO_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(settings.AUDIO_TEMP_DIR, f"{uuid.uuid4().hex}{original_ext}")

    try:
        # --- Persist upload to a temp file (Whisper needs a file path / on-disk audio) ---
        contents = await file.read()
        if not contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded audio file is empty.",
            )
        with open(temp_path, "wb") as f:
            f.write(contents)

        # --- Agent 1: transcription ---
        trace = AgentTrace()
        try:
            with trace.step(1, input={"audio_format": original_ext, "bytes": len(contents),
                                      "model": f"whisper {settings.WHISPER_MODEL_NAME}"},
                            messages_to=["Agent 2"]) as step:
                transcript = await run_in_threadpool(audio_service.transcribe_audio, temp_path)
                step["output"] = {"transcript": transcript, "characters": len(transcript)}
                step["summary"] = f"{len(transcript)} characters transcribed"
        except TranscriptionError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

        return await _run_pipeline(db, twilio, transcript, "audio", patient, trace=trace, n8n=n8n)

    except HTTPException:
        raise
    except Exception:
        # Logged with full traceback here; the client only ever sees the
        # generic body produced by the global handler in app/main.py.
        db.rollback()
        logger.exception("Unexpected error while processing triage request")
        raise
    finally:
        # --- Always clean up the temp audio file, success or failure ---
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning("Failed to remove temp audio file: %s", temp_path)


@router.post(
    "/process-triage/structured",
    response_model=TriageReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a triage report from typed symptoms (and optional vitals) instead of audio",
)
async def process_triage_structured(
    body: StructuredIntakeRequest,
    db: Session = Depends(get_db),
    twilio: TwilioService = Depends(get_twilio_service),
    n8n: N8nOrchestrator = Depends(get_n8n_orchestrator),
) -> TriageReportResponse:
    try:
        trace = AgentTrace()
        complaint = body.chief_complaint.strip()
        with trace.step(1, input={"intake_mode": "structured",
                                  "fields": sorted(body.model_dump(exclude_none=True))},
                        messages_to=["Agent 2"], agent_name="Intake (structured, no transcription needed)") as step:
            step["output"] = {"chief_complaint": complaint,
                              "vitals": body.vitals.model_dump(exclude_none=True) if body.vitals else None}
            step["summary"] = "typed complaint accepted"
        return await _run_pipeline(
            db, twilio, complaint, "structured",
            PatientContext(**body.model_dump(include={"patient_id", "age", "gender", "ethnicity"})),
            body.vitals, trace=trace, arrival_mode=body.arrival_mode, injury=body.injury, n8n=n8n,
        )
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Unexpected error while processing structured triage request")
        raise


def _loads(value: Optional[str]) -> List:
    try:
        return json.loads(value) if value else []
    except ValueError:
        return []


@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
    summary="Retrieve patient sessions, newest first, optionally filtered by severity",
)
def get_all_sessions(
    severity: Optional[SeverityLevel] = Query(None, description="Filter by triage level: High, Medium or Low"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Returns the patient list for the clinician dashboard, most recent
    first, with each session's latest clinician review (if any).
    """
    query = db.query(TriageSession)
    if severity:
        query = query.filter(TriageSession.severity == severity)
    sessions = query.order_by(TriageSession.created_at.desc()).limit(limit).all()

    latest = {}
    if sessions:
        ids = [s.id for s in sessions]
        for fb in (
            db.query(TriageSessionFeedback)
            .filter(TriageSessionFeedback.session_id.in_(ids))
            .order_by(TriageSessionFeedback.timestamp.asc())
        ):
            latest[fb.session_id] = fb

    data = []
    for s in sessions:
        fb = latest.get(s.id)
        data.append({
            "id": str(s.id),
            "created_at": s.created_at.isoformat(),
            "severity": s.severity.value if s.severity else None,
            "transcript": s.transcript,
            "chief_complaint": s.chief_complaint,
            "intake_mode": s.intake_mode,
            "duration": s.duration,
            # Kept as JSON-encoded strings for backwards compatibility with existing clients.
            "symptoms": s.symptoms,
            "possible_conditions": s.possible_conditions,
            "reasoning": s.reasoning,
            "required_actions": _loads(s.required_actions),
            "evidence_stay_ids": _loads(s.evidence_stay_ids),
            "patient_id": s.patient_id,
            "latest_feedback": fb.feedback.value if fb else None,
            # WP2-WP4 additions (None for sessions created before them)
            "evidence_scores": _loads(s.evidence_scores),
            "evidence_strength": s.evidence_strength,
            "low_evidence": s.low_evidence,
            "top_similarity": s.top_similarity,
            "llm_severity": s.llm_severity,
            "news2_score": s.news2_score,
            "safety_override": s.safety_override,
            "override_reason": s.override_reason,
            "has_trace": bool(s.agent_trace),
        })

    total = db.query(func.count(TriageSession.id))
    if severity:
        total = total.filter(TriageSession.severity == severity)
    return {"status": "success", "count": len(data), "total": total.scalar(), "data": data}


@router.get(
    "/sessions/{session_id}/trace",
    status_code=status.HTTP_200_OK,
    summary="Step-by-step agent trace of one triage session (WP4)",
)
def get_session_trace(session_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid session_id")
    record = db.get(TriageSession, sid)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    steps = _loads(record.agent_trace)
    # Agent 6 / 7 entries are appended to the stored trace when feedback or a drift run touches the session.
    return {
        "session_id": str(record.id),
        "created_at": record.created_at.isoformat(),
        "severity": record.severity.value if record.severity else None,
        "intake_mode": record.intake_mode,
        "steps": steps,
        "count": len(steps),
    }
