"""Agent 7 -- performance drift, data drift and bias detection."""

from collections import Counter
from datetime import datetime, timedelta

from app.models.mimic_models import SeverityLevel
from app.models.monitoring_models import AlertLog, DriftMetrics, FeedbackVerdict, TriageSessionFeedback
from app.services import drift_service
from scripts.seed_monitoring_demo import generate_demo_sessions

NOW = datetime(2026, 10, 26, 12, 0, 0)
# The MIMIC sample in conftest is 4 M / 4 F, severity 3 High / 3 Medium / 2 Low.
BALANCED = dict(genders=("M", "F"),
                severities=(SeverityLevel.HIGH, SeverityLevel.MEDIUM, SeverityLevel.LOW))  # period 6: gender and severity uncorrelated


def test_ethnicity_groups_and_age_bands():
    assert drift_service.ethnicity_group("WHITE - OTHER EUROPEAN") == "WHITE"
    assert drift_service.ethnicity_group("HISPANIC/LATINO - PUERTO RICAN") == "HISPANIC"
    assert drift_service.ethnicity_group("UNABLE TO OBTAIN") == "UNKNOWN"
    assert drift_service.age_band(70) == "65+" and drift_service.age_band(None) is None


def test_js_distance_bounds():
    same = Counter(M=50, F=50)
    assert drift_service.js_distance(same, same) < 0.01
    assert drift_service.js_distance(Counter(F=100), same) > 0.3


def test_healthy_system_has_no_drift_or_alerts(db):
    generate_demo_sessions(db, n=24, accuracy=0.95, now=NOW, **BALANCED)
    result = drift_service.run_drift_check(db, now=NOW)
    assert result["retraining_needed"] is False
    assert result["data_drift_detected"] is False
    assert result["drift_score"] < 0.3
    assert db.query(AlertLog).count() == 0
    assert db.query(DriftMetrics).count() == 1


def test_low_accuracy_triggers_retraining_alert_once(db):
    generate_demo_sessions(db, n=20, accuracy=0.7, now=NOW, **BALANCED)
    first = drift_service.run_drift_check(db, now=NOW)
    assert first["retraining_needed"] and first["performance"]["below_threshold"]
    assert [a["alert_type"] for a in first["alerts"] if a["raised"]] == ["performance_drift"]

    second = drift_service.run_drift_check(db, now=NOW)
    assert second["retraining_needed"]
    assert not any(a["raised"] for a in second["alerts"])  # de-duplicated within 24h
    assert db.query(AlertLog).filter_by(alert_type="performance_drift").count() == 1


def test_too_little_feedback_does_not_alert(db):
    generate_demo_sessions(db, n=5, accuracy=0.2, now=NOW, **BALANCED)
    result = drift_service.run_drift_check(db, now=NOW)
    assert result["performance"]["sufficient_data"] is False
    assert result["retraining_needed"] is False


def test_declining_trend_is_detected_even_above_threshold(db):
    # First half of the window: 100% correct; second half: ~87% correct.
    generate_demo_sessions(db, n=15, accuracy=1.0, now=NOW - timedelta(days=15), days=15, seed=1, **BALANCED)
    generate_demo_sessions(db, n=15, accuracy=0.87, now=NOW, days=15, seed=2, **BALANCED)
    perf = drift_service.run_drift_check(db, now=NOW)["performance"]
    assert perf["accuracy_30d"] >= 0.85 and perf["declining"] and perf["retraining_needed"]


def test_demographic_shift_is_data_drift(db):
    generate_demo_sessions(db, n=20, accuracy=1.0, now=NOW, genders=("F",), severities=BALANCED["severities"])
    result = drift_service.run_drift_check(db, now=NOW)
    assert result["drift_features"]["gender"]["score"] > 0.3
    assert result["data_drift_detected"] and result["drift_score"] > 0.3
    assert db.query(AlertLog).filter_by(alert_type="data_drift").count() == 1


def test_error_disparity_by_gender_is_bias(db):
    sessions = generate_demo_sessions(db, n=40, accuracy=1.0, now=NOW, reviewed_fraction=0.0, **BALANCED)
    for s in sessions:
        wrong = s.gender == "F" and int(s.patient_id[-3:]) % 8 != 1  # women: 75% wrong; men: always right
        db.add(TriageSessionFeedback(session_id=s.id, timestamp=NOW,
                                     feedback=FeedbackVerdict.INCORRECT if wrong else FeedbackVerdict.CORRECT))
    db.commit()
    result = drift_service.run_drift_check(db, now=NOW)
    gender = result["bias_scores_by_demographic"]["gender"]
    assert gender["error_disparity"]["p_value"] < 0.05
    assert gender["accuracy_by_group"]["M"] == 1.0 and gender["accuracy_by_group"]["F"] < 0.5
    assert gender["bias_detected"] and result["bias_detected"]


def test_age_outcome_disparity_is_not_flagged_as_bias(db):
    sessions = generate_demo_sessions(db, n=40, accuracy=1.0, now=NOW, **BALANCED)
    for s in sessions:  # older patients sicker -- clinically expected
        s.age = 80 if s.severity == SeverityLevel.HIGH else 25
    db.commit()
    age = drift_service.run_drift_check(db, now=NOW)["bias_scores_by_demographic"]["age_band"]
    assert age["outcome_disparity"]["p_value"] < 0.05
    assert age["bias_detected"] is False
