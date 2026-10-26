"""
Generates synthetic triage sessions with clinician feedback so the
monitoring (Agent 6) and drift/bias (Agent 7) dashboards have something
to show. Also used by the test suite as a deterministic fixture.

The sessions are clearly synthetic (patient_id "DEMO-xxx", transcript
prefixed "[DEMO]"). Never run this against a database that holds real
patient sessions.

Usage:
    python -m scripts.seed_monitoring_demo --sessions 30 --accuracy 0.8
    python -m scripts.seed_monitoring_demo --purge     # remove demo rows again
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.mimic_models import SeverityLevel, TriageSession
from app.models.monitoring_models import AlertLog, FeedbackVerdict, TriageSessionFeedback

DEMO_PREFIX = "[DEMO]"

_COMPLAINTS = [
    ("Crushing chest pain radiating to my left arm", SeverityLevel.HIGH),
    ("I can't catch my breath and my lips feel tingly", SeverityLevel.HIGH),
    ("Sudden worst headache of my life", SeverityLevel.HIGH),
    ("Stomach pain and vomiting since last night", SeverityLevel.MEDIUM),
    ("I fell and my wrist is swollen", SeverityLevel.MEDIUM),
    ("Fever and burning when I pee", SeverityLevel.MEDIUM),
    ("Runny nose and a mild sore throat", SeverityLevel.LOW),
    ("Twisted my ankle playing football, can walk on it", SeverityLevel.LOW),
]
_ETHNICITIES = ["WHITE", "BLACK/AFRICAN AMERICAN", "ASIAN", "HISPANIC/LATINO", "OTHER"]


def generate_demo_sessions(
    db: Session,
    n: int = 30,
    accuracy: float = 0.8,
    now: Optional[datetime] = None,
    days: int = 30,
    seed: int = 7,
    genders: Sequence[str] = ("M", "F"),
    severities: Optional[Sequence[SeverityLevel]] = None,
    reviewed_fraction: float = 1.0,
) -> List[TriageSession]:
    """
    Inserts `n` sessions spread evenly over the last `days` days, and
    reviews `reviewed_fraction` of them with exactly round(accuracy * reviewed)
    marked correct (deterministic for a given seed).
    """
    rng = random.Random(seed)
    now = now or datetime.utcnow()
    sessions = []
    for i in range(n):
        complaint, severity = _COMPLAINTS[i % len(_COMPLAINTS)]
        if severities:
            severity = severities[i % len(severities)]
        created = now - timedelta(days=days * (i + 0.5) / n)
        s = TriageSession(
            transcript=f"{DEMO_PREFIX} {complaint}",
            chief_complaint=complaint,
            intake_mode="structured",
            symptoms=json.dumps([complaint]),
            duration="Unknown",
            possible_conditions=json.dumps([]),
            severity=severity,
            reasoning="Synthetic demo session.",
            required_actions=json.dumps([]),
            evidence_stay_ids=json.dumps([]),
            patient_id=f"DEMO-{i:03d}",
            age=rng.randint(18, 90),
            gender=genders[i % len(genders)],
            ethnicity=_ETHNICITIES[i % len(_ETHNICITIES)],
            created_at=created,
        )
        db.add(s)
        sessions.append(s)
    db.flush()

    reviewed = sessions[: round(n * reviewed_fraction)]
    n_correct = round(accuracy * len(reviewed))
    incorrect_idx = set(rng.sample(range(len(reviewed)), len(reviewed) - n_correct))
    for i, s in enumerate(reviewed):
        verdict = FeedbackVerdict.INCORRECT if i in incorrect_idx else FeedbackVerdict.CORRECT
        db.add(TriageSessionFeedback(
            session_id=s.id,
            feedback=verdict,
            feedback_notes="Synthetic demo review.",
            reviewed_by="demo-clinician",
            flagged_for_review=verdict == FeedbackVerdict.INCORRECT,
            timestamp=s.created_at + timedelta(hours=1),
        ))
    db.commit()
    return sessions


def purge_demo_sessions(db: Session) -> int:
    ids = [sid for (sid,) in db.query(TriageSession.id).filter(TriageSession.transcript.like(f"{DEMO_PREFIX}%"))]
    if not ids:
        return 0
    db.query(TriageSessionFeedback).filter(TriageSessionFeedback.session_id.in_(ids)).delete(synchronize_session=False)
    db.query(AlertLog).filter(AlertLog.session_id.in_(ids)).delete(synchronize_session=False)
    db.query(TriageSession).filter(TriageSession.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return len(ids)


def main() -> None:
    from app.db.schema import ensure_schema
    from app.db.session import SessionLocal, engine

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sessions", type=int, default=30)
    parser.add_argument("--accuracy", type=float, default=0.8)
    parser.add_argument("--purge", action="store_true", help="Delete previously seeded demo sessions")
    args = parser.parse_args()

    ensure_schema(engine)
    db = SessionLocal()
    try:
        if args.purge:
            print(f"Removed {purge_demo_sessions(db)} demo sessions.")
        else:
            generate_demo_sessions(db, n=args.sessions, accuracy=args.accuracy)
            print(f"Inserted {args.sessions} demo sessions (target accuracy {args.accuracy:.0%}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
