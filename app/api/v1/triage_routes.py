"""
Triage API routes.

POST /process-triage (audio) and POST /process-triage/structured (typed
symptoms + optional vitals) share one pipeline:
  1. Agent 1 -- transcribe the audio (audio intake only).
  2. Agent 2 -- retrieve similar historical cases across all MIMIC tables.
  3. Agent 3 -- generate the triage report with the LLM, grounded in them.
  4. Agent 4 -- validate the report against the TriageResult schema.
  5. Persist a TriageSession record for audit and monitoring (Agent 6).
  6. Agent 5 -- send a WhatsApp alert when the severity requires one.
The temp audio file is always cleaned up, even on failure.

Blocking work (Whisper, the Groq call, Twilio retries) runs in the
threadpool so one slow request doesn't stall the event loop.
"""

import json
import logging
import os
import uuid
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
from app.services import audio_service, llm_service, retrieval_service
from app.services.audio_service import TranscriptionError
from app.services.llm_service import LLMGenerationError
from app.services.twilio_service import TwilioService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["Triage"])

_ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}


@lru_cache
def get_twilio_service() -> TwilioService:
    """FastAPI dependency; overridden in tests with a mocked client."""
    return TwilioService()


async def _run_pipeline(
    db: Session,
    twilio: TwilioService,
    transcript: str,
    intake_mode: str,
    patient: PatientContext,
    vitals: Optional[VitalsInput] = None,
) -> TriageReportResponse:
    # --- Agent 2: historical evidence retrieval ---
    similar_cases = retrieval_service.find_similar_cases(
        db, transcript, vitals.model_dump() if vitals else None
    )
    db_context = retrieval_service.format_cases_as_context(similar_cases)

    # --- Agents 3 + 4: LLM reasoning, validated against TriageResult ---
    try:
        triage_result = await run_in_threadpool(llm_service.generate_triage_report, transcript, db_context)
    except LLMGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    # --- Persist an audit record of this session ---
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
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)
    session_id = str(session_record.id)

    # --- Agent 5: proactive alert for high-severity cases ---
    alert = None
    if twilio.should_alert(triage_result.Severity.value):
        outcome = await run_in_threadpool(
            twilio.send_whatsapp_alert,
            patient.patient_id,
            triage_result.Severity.value,
            triage_result.Reasoning,
            transcript,
            session_id,
            db,
        )
        alert = AlertDispatchSchema(**outcome)

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
        try:
            transcript = await run_in_threadpool(audio_service.transcribe_audio, temp_path)
        except TranscriptionError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

        return await _run_pipeline(db, twilio, transcript, "audio", patient)

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
) -> TriageReportResponse:
    try:
        return await _run_pipeline(
            db, twilio, body.chief_complaint.strip(), "structured",
            PatientContext(**body.model_dump(include={"patient_id", "age", "gender", "ethnicity"})),
            body.vitals,
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
        })

    total = db.query(func.count(TriageSession.id))
    if severity:
        total = total.filter(TriageSession.severity == severity)
    return {"status": "success", "count": len(data), "total": total.scalar(), "data": data}
