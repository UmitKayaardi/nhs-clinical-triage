"""
Agent 7 -- Drift Detection & Bias Monitor.

Runs over the last MONITORING_WINDOW_DAYS (default 30) of triage
sessions and answers three questions:

1. Performance drift -- is the assistant getting worse?
   Clinician-reviewed accuracy below ACCURACY_ALERT_THRESHOLD (85%), or a
   drop of more than 5 percentage points between the first and second
   half of the window, means retraining/re-prompting is needed. Requires
   MIN_FEEDBACK_FOR_ACCURACY_ALERT reviews so a handful of verdicts can't
   trigger an alert.

2. Data drift -- do today's patients look like the reference data?
   Categorical features (gender, ethnicity group, predicted severity mix)
   are compared with the MIMIC-IV-ED reference population using the
   Jensen-Shannon distance (the symmetric, bounded form of KL divergence,
   in [0, 1]). Age is compared with a two-sample Kolmogorov-Smirnov test
   against the preceding 90 days of sessions, because MIMIC-IV-ED's ED
   tables carry no age column. drift_score is the largest of these
   per-feature scores; above DRIFT_SCORE_THRESHOLD (0.3) it is drift.

3. Bias -- do outcomes depend on demographics?
   For gender, age band and ethnicity group, a chi-squared test of
   independence is run on two tables:
   - severity x group ("outcome disparity", the spec's test), and
   - correct/incorrect x group ("error disparity", only with feedback).
   Error disparity is the real fairness signal: the model is wrong more
   often for one group. Severity genuinely varies with age, so an age
   outcome disparity is reported as expected clinical variation, not as
   bias. A significant gender/ethnicity outcome disparity or any
   significant error disparity sets bias_detected. Cramér's V is
   reported as the effect size.

Alerts (performance drift, data drift, bias) are written to AlertLog and
critical ones emailed to the admin; each type is raised at most once per
24 hours so refreshing the dashboard doesn't spam.
"""

import json
import logging
import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy import stats
from scipy.spatial.distance import jensenshannon
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.mimic_models import EDStay, SeverityLevel, Triage, TriageSession
from app.models.monitoring_models import DriftMetrics, FeedbackVerdict
from app.services import monitoring_service
from app.services.alert_service import raise_alert, recent_alert_exists

logger = logging.getLogger(__name__)

SEVERITIES = [s.value for s in SeverityLevel]
AGE_BANDS = [(0, 17, "0-17"), (18, 39, "18-39"), (40, 64, "40-64"), (65, 200, "65+")]
TREND_DROP_THRESHOLD = 0.05
AGE_BASELINE_DAYS = 90


def ethnicity_group(value: Optional[str]) -> str:
    """Collapses MIMIC race strings ("WHITE - OTHER EUROPEAN") and free text into coarse groups."""
    v = (value or "").upper()
    if not v or "UNKNOWN" in v or "UNABLE" in v or "DECLINED" in v:
        return "UNKNOWN"
    if "HISPANIC" in v or "LATINO" in v:
        return "HISPANIC"
    for group in ("WHITE", "BLACK", "ASIAN"):
        if group in v:
            return group
    return "OTHER"


def age_band(age: Optional[int]) -> Optional[str]:
    if age is None:
        return None
    for lo, hi, label in AGE_BANDS:
        if lo <= age <= hi:
            return label
    return None


def _distribution(counts: Counter, categories: Sequence[str]) -> np.ndarray:
    # Laplace smoothing keeps the distance finite when a category is unseen.
    arr = np.array([counts.get(c, 0) for c in categories], dtype=float) + 0.5
    return arr / arr.sum()


def js_distance(current: Counter, reference: Counter) -> float:
    categories = sorted(set(current) | set(reference))
    if len(categories) < 2:
        return 0.0
    return float(jensenshannon(_distribution(current, categories), _distribution(reference, categories), base=2))


def _reference_counts(db: Session) -> Dict[str, Counter]:
    gender = Counter(dict(db.query(EDStay.gender, func.count()).filter(EDStay.gender.isnot(None)).group_by(EDStay.gender).all()))
    ethnicity = Counter()
    for race, n in db.query(EDStay.race, func.count()).group_by(EDStay.race).all():
        ethnicity[ethnicity_group(race)] += n
    severity = Counter()
    for sev, n in db.query(Triage.severity, func.count()).filter(Triage.severity.isnot(None)).group_by(Triage.severity).all():
        severity[sev.value] += n
    return {"gender": gender, "ethnicity": ethnicity, "severity": severity}


def _window_sessions(db: Session, since: datetime, until: datetime) -> List[TriageSession]:
    return (
        db.query(TriageSession)
        .filter(TriageSession.created_at >= since, TriageSession.created_at < until)
        .all()
    )


def performance_drift(db: Session, now: datetime) -> Dict:
    settings = get_settings()
    window = settings.MONITORING_WINDOW_DAYS
    summary = monitoring_service.accuracy_summary(db, window_days=window, now=now)
    half = now - timedelta(days=window / 2)
    first = monitoring_service._latest_reviews(db, now - timedelta(days=window), half)
    second = monitoring_service._latest_reviews(db, half, now)
    acc_first, _ = monitoring_service._rates(first)
    acc_second, _ = monitoring_service._rates(second)

    min_n = settings.MIN_FEEDBACK_FOR_ACCURACY_ALERT
    enough = summary["reviewed_sessions"] >= min_n
    below_threshold = enough and summary["accuracy_30d"] < settings.ACCURACY_ALERT_THRESHOLD
    declining = (
        acc_first is not None and acc_second is not None
        and len(first) >= min_n // 2 and len(second) >= min_n // 2
        and (acc_first - acc_second) > TREND_DROP_THRESHOLD
    )

    slope = None
    trend = summary["trend"]
    if len(trend) >= 3:
        x = [(datetime.fromisoformat(d["date"]) - now).days for d in trend]
        slope = round(float(stats.linregress(x, [d["accuracy"] for d in trend]).slope), 5)

    return {
        "accuracy_30d": summary["accuracy_30d"],
        "hallucination_rate": summary["hallucination_rate"],
        "reviewed_sessions": summary["reviewed_sessions"],
        "accuracy_first_half": round(acc_first, 4) if acc_first is not None else None,
        "accuracy_second_half": round(acc_second, 4) if acc_second is not None else None,
        "daily_accuracy_slope": slope,
        "below_threshold": bool(below_threshold),
        "declining": bool(declining),
        "retraining_needed": bool(below_threshold or declining),
        "sufficient_data": enough,
        "trend": trend,
    }


def data_drift(db: Session, sessions: List[TriageSession], now: datetime) -> Dict:
    settings = get_settings()
    min_n = settings.MIN_SESSIONS_FOR_DRIFT
    reference = _reference_counts(db)
    current = {
        "gender": Counter(s.gender for s in sessions if s.gender),
        "ethnicity": Counter(ethnicity_group(s.ethnicity) for s in sessions if s.ethnicity),
        "severity": Counter(s.severity.value for s in sessions if s.severity),
    }

    features = {}
    for name, counts in current.items():
        n = sum(counts.values())
        score = js_distance(counts, reference[name]) if n >= min_n else None
        features[name] = {
            "test": "jensen_shannon",
            "score": round(score, 4) if score is not None else None,
            "n": n,
            "current": dict(counts),
            "reference": dict(reference[name]),
        }

    window_start = now - timedelta(days=settings.MONITORING_WINDOW_DAYS)
    baseline = _window_sessions(db, window_start - timedelta(days=AGE_BASELINE_DAYS), window_start)
    ages_now = [s.age for s in sessions if s.age is not None]
    ages_base = [s.age for s in baseline if s.age is not None]
    age_feature = {"test": "kolmogorov_smirnov", "score": None, "p_value": None,
                   "n": len(ages_now), "n_baseline": len(ages_base)}
    if len(ages_now) >= min_n and len(ages_base) >= min_n:
        ks = stats.ks_2samp(ages_now, ages_base)
        age_feature.update(score=round(float(ks.statistic), 4), p_value=round(float(ks.pvalue), 4))
    features["age"] = age_feature

    scored = [f["score"] for f in features.values() if f["score"] is not None]
    drift_score = max(scored) if scored else None
    return {
        "drift_score": drift_score,
        "drift_detected": bool(drift_score is not None and drift_score > settings.DRIFT_SCORE_THRESHOLD),
        "features": features,
    }


def _chi_squared(rows: List[str], cols: List[str]) -> Optional[Dict]:
    """Chi-squared test of independence between two paired categorical lists."""
    row_levels = sorted(set(rows))
    col_levels = sorted(set(cols))
    if len(row_levels) < 2 or len(col_levels) < 2:
        return None
    table = np.zeros((len(row_levels), len(col_levels)))
    for r, c in zip(rows, cols):
        table[row_levels.index(r), col_levels.index(c)] += 1
    chi2, p, dof, _ = stats.chi2_contingency(table)
    n = table.sum()
    cramers_v = math.sqrt(chi2 / (n * (min(table.shape) - 1))) if n else 0.0
    return {"chi2": round(float(chi2), 4), "p_value": round(float(p), 4), "dof": int(dof),
            "cramers_v": round(cramers_v, 4), "n": int(n)}


def bias_check(db: Session, sessions: List[TriageSession]) -> Dict:
    settings = get_settings()
    min_n = settings.MIN_SESSIONS_FOR_DRIFT
    alpha = settings.BIAS_P_VALUE_THRESHOLD

    verdicts = {}
    if sessions:
        reviews = monitoring_service._latest_reviews(db, min(s.created_at for s in sessions))
        verdicts = {r.session_id: r.verdict for r in reviews}

    getters = {
        "gender": lambda s: s.gender,
        "age_band": lambda s: age_band(s.age),
        "ethnicity": lambda s: ethnicity_group(s.ethnicity) if s.ethnicity else None,
    }

    results, any_bias = {}, False
    for name, get_group in getters.items():
        pairs = [(get_group(s), s.severity.value) for s in sessions if get_group(s) and s.severity]
        outcome = _chi_squared([p[1] for p in pairs], [p[0] for p in pairs]) if len(pairs) >= min_n else None

        reviewed = [(get_group(s), verdicts[s.id]) for s in sessions if get_group(s) and s.id in verdicts]
        error = None
        accuracy_by_group = {}
        if reviewed:
            for group in sorted({g for g, _ in reviewed}):
                vs = [v for g, v in reviewed if g == group]
                accuracy_by_group[group] = round(sum(v == FeedbackVerdict.CORRECT for v in vs) / len(vs), 4)
            if len(reviewed) >= min_n:
                error = _chi_squared([v.value for _, v in reviewed], [g for g, _ in reviewed])

        outcome_flag = bool(outcome and outcome["p_value"] < alpha and name != "age_band")
        error_flag = bool(error and error["p_value"] < alpha)
        any_bias = any_bias or outcome_flag or error_flag
        results[name] = {
            "outcome_disparity": outcome,
            "error_disparity": error,
            "accuracy_by_group": accuracy_by_group,
            "severity_by_group": {
                g: dict(Counter(sev for gg, sev in pairs if gg == g)) for g in sorted({g for g, _ in pairs})
            },
            "bias_detected": outcome_flag or error_flag,
            "note": "Severity naturally varies with age; only error disparity is treated as bias."
            if name == "age_band" else None,
        }
    return {"bias_detected": any_bias, "by_demographic": results}


def _daily_volume(sessions: List[TriageSession]) -> List[Dict]:
    by_day: Dict[str, Counter] = {}
    for s in sessions:
        day = s.created_at.date().isoformat()
        by_day.setdefault(day, Counter())[s.severity.value if s.severity else "Unknown"] += 1
    return [{"date": d, "sessions": sum(c.values()), **{k: c.get(k, 0) for k in SEVERITIES}} for d, c in sorted(by_day.items())]


def run_drift_check(db: Session, now: Optional[datetime] = None, persist: bool = True,
                    raise_alerts: bool = True) -> Dict:
    """
    Runs all three checks. When `persist`, stores a DriftMetrics snapshot;
    when `raise_alerts`, logs/emails alerts for anything detected.
    Returns the JSON served by GET /api/v1/admin/drift.
    """
    settings = get_settings()
    now = now or datetime.utcnow()
    sessions = _window_sessions(db, now - timedelta(days=settings.MONITORING_WINDOW_DAYS), now)

    perf = performance_drift(db, now)
    drift = data_drift(db, sessions, now)
    bias = bias_check(db, sessions)

    alerts: List[Dict] = []

    def _alert(alert_type: str, severity: str, message: str) -> None:
        entry = {"alert_type": alert_type, "severity": severity, "message": message, "raised": False}
        if raise_alerts and not recent_alert_exists(db, alert_type, now=now):
            raise_alert(db, alert_type, severity, message, timestamp=now)
            entry["raised"] = True
        alerts.append(entry)

    if perf["retraining_needed"]:
        reasons = []
        if perf["below_threshold"]:
            reasons.append(f"30-day accuracy {perf['accuracy_30d']:.0%} < {settings.ACCURACY_ALERT_THRESHOLD:.0%}")
        if perf["declining"]:
            reasons.append(f"accuracy fell from {perf['accuracy_first_half']:.0%} to {perf['accuracy_second_half']:.0%}")
        _alert("performance_drift", "critical", "Retraining/re-prompting recommended: " + "; ".join(reasons))
    if drift["drift_detected"]:
        worst = max((k for k, f in drift["features"].items() if f["score"] is not None),
                    key=lambda k: drift["features"][k]["score"])
        _alert("data_drift", "critical",
               f"Data drift score {drift['drift_score']:.2f} > {settings.DRIFT_SCORE_THRESHOLD} (largest shift: {worst})")
    if bias["bias_detected"]:
        groups = [k for k, v in bias["by_demographic"].items() if v["bias_detected"]]
        _alert("bias", "warning", f"Possible bias in triage outcomes by: {', '.join(groups)}. Clinical review required.")

    if persist:
        db.add(DriftMetrics(
            timestamp=now,
            accuracy_30d=perf["accuracy_30d"],
            hallucination_rate=perf["hallucination_rate"],
            drift_score=drift["drift_score"],
            bias_by_demographic=json.dumps({k: v["bias_detected"] for k, v in bias["by_demographic"].items()}),
            retraining_needed=perf["retraining_needed"],
        ))
        db.commit()

    history = (
        db.query(DriftMetrics).order_by(DriftMetrics.timestamp.desc()).limit(30).all()
    )
    return {
        "timestamp": now.isoformat(),
        "window_days": settings.MONITORING_WINDOW_DAYS,
        "sessions_in_window": len(sessions),
        "drift_detected": drift["drift_detected"] or perf["retraining_needed"],
        "data_drift_detected": drift["drift_detected"],
        "bias_detected": bias["bias_detected"],
        "retraining_needed": perf["retraining_needed"],
        "drift_score": drift["drift_score"],
        "performance": perf,
        "drift_features": drift["features"],
        "bias_scores_by_demographic": bias["by_demographic"],
        "alerts": alerts,
        "trend_graph_data": {
            "daily_accuracy": perf["trend"],
            "daily_volume": _daily_volume(sessions),
            "snapshots": [
                {"timestamp": m.timestamp.isoformat(), "accuracy_30d": m.accuracy_30d,
                 "hallucination_rate": m.hallucination_rate, "drift_score": m.drift_score,
                 "retraining_needed": m.retraining_needed}
                for m in reversed(history)
            ],
        },
    }
