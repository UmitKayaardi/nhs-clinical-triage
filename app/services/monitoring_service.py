"""
Agent 6 -- Post-Deployment Monitor.

Turns clinician feedback on triage sessions into post-market
surveillance (PMS) metrics:

- Feedback: a clinician marks a session "correct" or "incorrect". An
  "incorrect" verdict flags the session as a suspected hallucination for
  follow-up review. If a session is reviewed more than once, only the
  latest verdict counts.
- Accuracy: share of reviewed sessions marked correct, over a moving
  window (default: last 30 days, by session date).
- Hallucination rate: share of reviewed sessions marked incorrect in the
  same window. Every incorrect verdict is treated as a suspected
  hallucination until a reviewer clears it -- conservative by design.
- Monthly PMS report: one CSV row per day with sessions, reviews,
  correct, hallucinations, accuracy and alerts raised.

Every session itself (timestamp, patient_id, chief complaint, triage
level, evidence cases, reasoning) is already persisted by the triage
endpoint in TriageSession; this module only reads it.
"""

import csv
import io
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.mimic_models import TriageSession
from app.models.monitoring_models import AlertLog, FeedbackVerdict, TriageSessionFeedback


class SessionNotFoundError(Exception):
    """Raised when feedback references a session that does not exist."""


@dataclass
class ReviewedSession:
    session_id: uuid.UUID
    created_at: datetime
    severity: Optional[str]
    verdict: FeedbackVerdict


def record_feedback(
    db: Session,
    session_id: str,
    feedback: str,
    notes: Optional[str] = None,
    reviewed_by: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> TriageSessionFeedback:
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError as exc:
        raise SessionNotFoundError(f"Invalid session id: {session_id}") from exc
    if db.get(TriageSession, sid) is None:
        raise SessionNotFoundError(f"Session {session_id} not found")

    verdict = FeedbackVerdict(feedback)
    row = TriageSessionFeedback(
        session_id=sid,
        feedback=verdict,
        feedback_notes=notes,
        reviewed_by=reviewed_by,
        flagged_for_review=verdict == FeedbackVerdict.INCORRECT,
        timestamp=timestamp or datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _latest_reviews(db: Session, since: datetime, until: Optional[datetime] = None) -> List[ReviewedSession]:
    """Latest verdict per session, for sessions created in [since, until)."""
    latest_ts = (
        db.query(
            TriageSessionFeedback.session_id.label("sid"),
            func.max(TriageSessionFeedback.timestamp).label("ts"),
        )
        .group_by(TriageSessionFeedback.session_id)
        .subquery()
    )
    query = (
        db.query(TriageSession.id, TriageSession.created_at, TriageSession.severity, TriageSessionFeedback.feedback)
        .join(latest_ts, latest_ts.c.sid == TriageSession.id)
        .join(
            TriageSessionFeedback,
            (TriageSessionFeedback.session_id == latest_ts.c.sid) & (TriageSessionFeedback.timestamp == latest_ts.c.ts),
        )
        .filter(TriageSession.created_at >= since)
    )
    if until is not None:
        query = query.filter(TriageSession.created_at < until)

    seen = set()
    reviews = []
    for sid, created_at, severity, verdict in query.all():
        if sid in seen:  # two reviews with an identical timestamp: keep one
            continue
        seen.add(sid)
        reviews.append(ReviewedSession(sid, created_at, severity.value if severity else None, verdict))
    return reviews


def _rates(reviews: List[ReviewedSession]) -> Tuple[Optional[float], Optional[float]]:
    if not reviews:
        return None, None
    correct = sum(1 for r in reviews if r.verdict == FeedbackVerdict.CORRECT)
    return correct / len(reviews), (len(reviews) - correct) / len(reviews)


def daily_accuracy(reviews: List[ReviewedSession]) -> List[Dict]:
    by_day: Dict[date, List[ReviewedSession]] = defaultdict(list)
    for r in reviews:
        by_day[r.created_at.date()].append(r)
    out = []
    for day in sorted(by_day):
        acc, hall = _rates(by_day[day])
        out.append({
            "date": day.isoformat(),
            "reviewed": len(by_day[day]),
            "accuracy": round(acc, 4),
            "hallucination_rate": round(hall, 4),
        })
    return out


def accuracy_summary(db: Session, window_days: Optional[int] = None, now: Optional[datetime] = None) -> Dict:
    """
    Returns the JSON served by GET /api/v1/admin/accuracy:
    {accuracy_30d, hallucination_rate, reviewed_sessions, total_sessions,
     flagged_for_review, trend: [{date, reviewed, accuracy, hallucination_rate}], ...}
    Rates are None when there is no feedback in the window.
    """
    settings = get_settings()
    window_days = window_days or settings.MONITORING_WINDOW_DAYS
    now = now or datetime.utcnow()
    since = now - timedelta(days=window_days)

    reviews = _latest_reviews(db, since)
    accuracy, hallucination_rate = _rates(reviews)
    total_sessions = db.query(func.count(TriageSession.id)).filter(TriageSession.created_at >= since).scalar()

    per_severity = {}
    for level in ("High", "Medium", "Low"):
        subset = [r for r in reviews if r.severity == level]
        acc, _ = _rates(subset)
        per_severity[level] = {"reviewed": len(subset), "accuracy": round(acc, 4) if acc is not None else None}

    return {
        "window_days": window_days,
        "accuracy_30d": round(accuracy, 4) if accuracy is not None else None,
        "hallucination_rate": round(hallucination_rate, 4) if hallucination_rate is not None else None,
        "reviewed_sessions": len(reviews),
        "total_sessions": total_sessions,
        "review_coverage": round(len(reviews) / total_sessions, 4) if total_sessions else None,
        "flagged_for_review": sum(1 for r in reviews if r.verdict == FeedbackVerdict.INCORRECT),
        "accuracy_by_severity": per_severity,
        "trend": daily_accuracy(reviews),
    }


def flagged_sessions(db: Session, limit: int = 50) -> List[Dict]:
    """Sessions whose latest review is "incorrect" -- the hallucination review queue."""
    reviews = _latest_reviews(db, since=datetime(1970, 1, 1))
    flagged_ids = [r.session_id for r in reviews if r.verdict == FeedbackVerdict.INCORRECT]
    if not flagged_ids:
        return []
    rows = (
        db.query(TriageSession)
        .filter(TriageSession.id.in_(flagged_ids))
        .order_by(TriageSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "session_id": str(s.id),
            "created_at": s.created_at.isoformat(),
            "severity": s.severity.value if s.severity else None,
            "chief_complaint": s.chief_complaint or s.transcript,
            "reasoning": s.reasoning,
        }
        for s in rows
    ]


PMS_COLUMNS = ["date", "total_sessions", "reviewed", "correct", "hallucinations", "accuracy_%", "alerts"]


def monthly_report_rows(db: Session, year: int, month: int) -> List[Dict]:
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), month % 12 + 1, 1)

    sessions_per_day = defaultdict(int)
    for (created_at,) in db.query(TriageSession.created_at).filter(
        TriageSession.created_at >= start, TriageSession.created_at < end
    ):
        sessions_per_day[created_at.date()] += 1

    alerts_per_day = defaultdict(int)
    for (ts,) in db.query(AlertLog.timestamp).filter(AlertLog.timestamp >= start, AlertLog.timestamp < end):
        alerts_per_day[ts.date()] += 1

    reviews_per_day: Dict[date, List[ReviewedSession]] = defaultdict(list)
    for r in _latest_reviews(db, start, end):
        reviews_per_day[r.created_at.date()].append(r)

    rows = []
    day = start.date()
    while day < end.date():
        reviews = reviews_per_day.get(day, [])
        correct = sum(1 for r in reviews if r.verdict == FeedbackVerdict.CORRECT)
        rows.append({
            "date": day.isoformat(),
            "total_sessions": sessions_per_day.get(day, 0),
            "reviewed": len(reviews),
            "correct": correct,
            "hallucinations": len(reviews) - correct,
            "accuracy_%": round(100 * correct / len(reviews), 1) if reviews else "",
            "alerts": alerts_per_day.get(day, 0),
        })
        day += timedelta(days=1)
    return rows


def monthly_report_csv(db: Session, year: int, month: int) -> str:
    """Monthly PMS report as CSV text, one row per calendar day plus a TOTAL row."""
    rows = monthly_report_rows(db, year, month)
    total_reviewed = sum(r["reviewed"] for r in rows)
    total_correct = sum(r["correct"] for r in rows)
    rows.append({
        "date": "TOTAL",
        "total_sessions": sum(r["total_sessions"] for r in rows),
        "reviewed": total_reviewed,
        "correct": total_correct,
        "hallucinations": total_reviewed - total_correct,
        "accuracy_%": round(100 * total_correct / total_reviewed, 1) if total_reviewed else "",
        "alerts": sum(r["alerts"] for r in rows),
    })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=PMS_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
