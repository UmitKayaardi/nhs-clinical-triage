"""
Monitoring, alerting and drift API routes (Agents 6 and 7).

  POST /api/v1/feedback                clinician marks a session correct/incorrect
  GET  /api/v1/admin/accuracy          30-day accuracy, hallucination rate, trend
  GET  /api/v1/admin/flagged           sessions flagged as suspected hallucinations
  GET  /api/v1/admin/pms-report        monthly post-market surveillance CSV
  GET  /api/v1/admin/drift             drift + bias check (stores a snapshot, raises alerts)
  POST /api/v1/alerts                  log an alert (critical ones are emailed)
  GET  /api/v1/alerts                  list alerts
  POST /api/v1/alerts/{id}/acknowledge mark an alert as handled

All routes are protected by X-Admin-Key when ADMIN_API_KEY is set.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.security import require_admin_key
from app.db.session import get_db
from app.models.monitoring_models import AlertLog
from app.schemas.monitoring_schema import AlertRequest, AlertResponse, FeedbackRequest, FeedbackResponse
from app.services import drift_service, monitoring_service
from app.services.alert_service import raise_alert
from app.services.monitoring_service import SessionNotFoundError

router = APIRouter(prefix="/api/v1", tags=["Monitoring"], dependencies=[Depends(require_admin_key)])


def _alert_out(alert: AlertLog) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
        status=alert.status,
        session_id=str(alert.session_id) if alert.session_id else None,
        timestamp=alert.timestamp,
        acknowledged=alert.acknowledged,
    )


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED,
             summary="Record a clinician's verdict on a triage session")
def submit_feedback(body: FeedbackRequest, db: Session = Depends(get_db)) -> FeedbackResponse:
    try:
        row = monitoring_service.record_feedback(db, body.session_id, body.feedback, body.notes, body.reviewed_by)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return FeedbackResponse(
        id=row.id,
        session_id=str(row.session_id),
        feedback=row.feedback.value,
        flagged_for_review=row.flagged_for_review,
        timestamp=row.timestamp,
    )


@router.get("/admin/accuracy", summary="Moving-window accuracy and hallucination rate")
def get_accuracy(window_days: Optional[int] = Query(None, ge=1, le=365), db: Session = Depends(get_db)) -> dict:
    return monitoring_service.accuracy_summary(db, window_days=window_days)


@router.get("/admin/flagged", summary="Sessions whose latest review is 'incorrect'")
def get_flagged(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    items = monitoring_service.flagged_sessions(db, limit=limit)
    return {"count": len(items), "data": items}


@router.get("/admin/pms-report", summary="Monthly post-market surveillance report (CSV)",
            response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def get_pms_report(
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    db: Session = Depends(get_db),
) -> Response:
    month = month or datetime.utcnow().strftime("%Y-%m")
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", month)
    if not match:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="month must be YYYY-MM")
    csv_text = monitoring_service.monthly_report_csv(db, int(match.group(1)), int(match.group(2)))
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="pms_report_{month}.csv"'},
    )


@router.get("/admin/drift", summary="Run the drift and bias check")
def get_drift(
    persist: bool = Query(True, description="Store a DriftMetrics snapshot and raise alerts"),
    db: Session = Depends(get_db),
) -> dict:
    return drift_service.run_drift_check(db, persist=persist, raise_alerts=persist)


@router.post("/alerts", response_model=AlertResponse, status_code=status.HTTP_201_CREATED,
             summary="Log an alert; critical alerts are emailed to the admin")
def create_alert(body: AlertRequest, db: Session = Depends(get_db)) -> AlertResponse:
    session_id = None
    if body.session_id:
        try:
            session_id = uuid.UUID(body.session_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid session_id")
    alert = raise_alert(db, body.alert_type, body.severity, body.message,
                        session_id=session_id, timestamp=body.timestamp)
    return _alert_out(alert)


@router.get("/alerts", summary="List alerts, newest first")
def list_alerts(
    unacknowledged_only: bool = False,
    alert_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(AlertLog)
    if unacknowledged_only:
        query = query.filter(AlertLog.acknowledged.is_(False))
    if alert_type:
        query = query.filter(AlertLog.alert_type == alert_type)
    alerts = query.order_by(AlertLog.timestamp.desc()).limit(limit).all()
    return {"count": len(alerts), "data": [_alert_out(a).model_dump(mode="json") for a in alerts]}


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertResponse, summary="Acknowledge an alert")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertResponse:
    alert = db.get(AlertLog, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    db.refresh(alert)
    return _alert_out(alert)
