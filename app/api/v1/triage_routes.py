"""
Triage API routes.

Exposes POST /process-triage, which orchestrates the full pipeline:
  1. Save the uploaded audio to a temp file.
  2. Transcribe it (audio_service).
  3. Retrieve similar historical cases (db_service).
  4. Generate the structured triage report (llm_service).
  5. Persist a TriageSession record for audit purposes.
  6. Clean up the temp file, always -- even on failure.
"""

import json
import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.mimic_models import TriageSession
from app.schemas.triage_schema import SimilarCaseSchema, TriageReportResponse
from app.services import audio_service, db_service, llm_service
from app.services.audio_service import TranscriptionError
from app.services.llm_service import LLMGenerationError

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["Triage"])

_ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}


@router.post(
    "/process-triage",
    response_model=TriageReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe patient audio and generate an evidence-grounded triage report",
)
async def process_triage(
    file: UploadFile = File(..., description="Patient audio recording"),
    db: Session = Depends(get_db),
) -> TriageReportResponse:
    """
    Full triage pipeline endpoint.

    Accepts a single audio file upload, runs it through transcription,
    historical-evidence retrieval, and LLM structuring, and returns the
    resulting report. A TriageSession row is persisted for every
    successful run so the evidence used for each report stays auditable.
    """
    original_ext = os.path.splitext(file.filename or "")[1].lower()
    if original_ext not in _ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format '{original_ext}'. "
            f"Allowed: {sorted(_ALLOWED_AUDIO_EXTENSIONS)}",
        )

    os.makedirs(settings.AUDIO_TEMP_DIR, exist_ok=True)
    temp_filename = f"{uuid.uuid4().hex}{original_ext}"
    temp_path = os.path.join(settings.AUDIO_TEMP_DIR, temp_filename)

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

        # --- Step 1: Transcription ---
        try:
            transcript = audio_service.transcribe_audio(temp_path)
        except TranscriptionError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

        # --- Step 2: Historical evidence retrieval ---
        similar_cases = db_service.find_similar_cases(db, transcript)
        db_context = db_service.format_cases_as_context(similar_cases)

        # --- Step 3: LLM structuring, grounded in db_context ---
        try:
            triage_result = llm_service.generate_triage_report(transcript, db_context)
        except LLMGenerationError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

        # --- Step 4: Persist an audit record of this session ---
        session_record = TriageSession(
            transcript=transcript,
            llm_raw_response=triage_result.model_dump_json(),
            symptoms=json.dumps(triage_result.Symptoms),
            duration=triage_result.Duration,
            possible_conditions=json.dumps(triage_result.Possible_Conditions),
            severity=triage_result.Severity,
            evidence_stay_ids=json.dumps([case.stay_id for case in similar_cases]),
        )
        db.add(session_record)
        db.commit()
        db.refresh(session_record)

        return TriageReportResponse(
            transcript=transcript,
            triage_result=triage_result,
            evidence_cases=[
                SimilarCaseSchema(
                    chief_complaint=case.chief_complaint,
                    icd_title=case.icd_title,
                    severity=case.severity,
                )
                for case in similar_cases
            ],
            session_id=str(session_record.id),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error while processing triage request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected server error: {exc}",
        )
    finally:
        # --- Always clean up the temp audio file, success or failure ---
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning("Failed to remove temp audio file: %s", temp_path)

@router.get(
    "/sessions",
    status_code=status.HTTP_200_OK,
    summary="Retrieve all patient sessions or filter by severity"
)
def get_all_sessions(
    severity: str = Query(None, description="Target severity level for filtering (e.g., Critical, High)"),
    db: Session = Depends(get_db)
):
    """
    Returns the patient list for the clinician dashboard.
    If the 'severity' parameter is provided, filters the records accordingly.
    """
    query = db.query(TriageSession)
    
    if severity:
        query = query.filter(TriageSession.severity == severity)
        
    sessions = query.all()
    # Reverse the list so the most recent patient appears at the top
    sessions.reverse() 
    
    return {
        "status": "success",
        "count": len(sessions),
        "data": sessions
    }