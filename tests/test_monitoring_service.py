"""Agent 6 -- feedback, accuracy, hallucination rate and the monthly PMS report."""

import csv
import io
from datetime import datetime, timedelta

import pytest

from app.models.monitoring_models import TriageSessionFeedback
from app.services import monitoring_service
from app.services.monitoring_service import SessionNotFoundError
from scripts.seed_monitoring_demo import generate_demo_sessions, purge_demo_sessions

NOW = datetime(2026, 10, 26, 12, 0, 0)


def test_accuracy_over_thirty_seeded_sessions(db):
    generate_demo_sessions(db, n=30, accuracy=0.8, now=NOW)
    summary = monitoring_service.accuracy_summary(db, now=NOW)
    assert summary["reviewed_sessions"] == 30
    assert summary["accuracy_30d"] == pytest.approx(0.8)
    assert summary["hallucination_rate"] == pytest.approx(0.2)
    assert summary["flagged_for_review"] == 6
    assert sum(d["reviewed"] for d in summary["trend"]) == 30


def test_window_excludes_old_sessions(db):
    generate_demo_sessions(db, n=10, accuracy=1.0, now=NOW)
    generate_demo_sessions(db, n=10, accuracy=0.0, now=NOW - timedelta(days=60), seed=3)
    assert monitoring_service.accuracy_summary(db, now=NOW)["accuracy_30d"] == 1.0
    assert monitoring_service.accuracy_summary(db, window_days=90, now=NOW)["accuracy_30d"] == 0.5


def test_no_feedback_gives_null_rates(db):
    generate_demo_sessions(db, n=5, accuracy=1.0, now=NOW, reviewed_fraction=0.0)
    summary = monitoring_service.accuracy_summary(db, now=NOW)
    assert summary["accuracy_30d"] is None and summary["hallucination_rate"] is None
    assert summary["total_sessions"] == 5 and summary["review_coverage"] == 0


def test_incorrect_feedback_flags_and_latest_verdict_wins(db):
    session = generate_demo_sessions(db, n=1, accuracy=1.0, now=NOW, reviewed_fraction=0.0)[0]
    first = monitoring_service.record_feedback(db, str(session.id), "incorrect", "Missed sepsis",
                                               timestamp=NOW - timedelta(minutes=5))
    assert first.flagged_for_review
    assert monitoring_service.flagged_sessions(db)[0]["session_id"] == str(session.id)

    monitoring_service.record_feedback(db, str(session.id), "correct", "Re-reviewed: fine", timestamp=NOW)
    assert monitoring_service.accuracy_summary(db, now=NOW)["accuracy_30d"] == 1.0
    assert monitoring_service.flagged_sessions(db) == []
    assert db.query(TriageSessionFeedback).count() == 2  # history is kept


def test_feedback_for_unknown_session_is_rejected(db):
    with pytest.raises(SessionNotFoundError):
        monitoring_service.record_feedback(db, "00000000-0000-0000-0000-000000000000", "correct")
    with pytest.raises(SessionNotFoundError):
        monitoring_service.record_feedback(db, "not-a-uuid", "correct")


def test_monthly_pms_report_csv(db):
    generate_demo_sessions(db, n=20, accuracy=0.75, now=datetime(2026, 10, 21), days=20)
    rows = list(csv.DictReader(io.StringIO(monitoring_service.monthly_report_csv(db, 2026, 10))))
    assert list(rows[0]) == monitoring_service.PMS_COLUMNS
    assert len(rows) == 31 + 1
    total = rows[-1]
    assert total["date"] == "TOTAL"
    assert (int(total["total_sessions"]), int(total["correct"]), int(total["hallucinations"])) == (20, 15, 5)
    assert float(total["accuracy_%"]) == 75.0


def test_purge_removes_only_demo_rows(db):
    generate_demo_sessions(db, n=4, now=NOW)
    assert purge_demo_sessions(db) == 4
    assert monitoring_service.accuracy_summary(db, now=NOW)["total_sessions"] == 0
