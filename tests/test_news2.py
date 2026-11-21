"""WP3 -- NEWS2 scoring against the RCP (2017) NEWS2 chart, and the raise-only safety net."""

import pytest

from app.services.news2 import (
    apply_safety_net,
    calculate_news2,
    minimum_severity,
    score_consciousness,
    score_pulse,
    score_resp_rate,
    score_sbp,
    score_spo2_scale1,
    score_temperature_c,
)
from app.services.vitals import c_to_f


@pytest.mark.parametrize("rr,score", [(8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3)])
def test_respiration_rate_chart(rr, score):
    assert score_resp_rate(rr) == score


@pytest.mark.parametrize("spo2,score", [(91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0)])
def test_spo2_scale1_chart(spo2, score):
    assert score_spo2_scale1(spo2) == score


@pytest.mark.parametrize("sbp,score", [(90, 3), (91, 2), (100, 2), (101, 1), (110, 1), (111, 0), (219, 0), (220, 3)])
def test_systolic_bp_chart(sbp, score):
    assert score_sbp(sbp) == score


@pytest.mark.parametrize("hr,score", [(40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2),
                                      (130, 2), (131, 3)])
def test_pulse_chart(hr, score):
    assert score_pulse(hr) == score


@pytest.mark.parametrize("temp,score", [(35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0), (38.1, 1),
                                        (39.0, 1), (39.1, 2)])
def test_temperature_chart(temp, score):
    assert score_temperature_c(temp) == score


def test_consciousness_alert_vs_cvpu():
    assert score_consciousness("alert") == 0
    for level in ("confusion", "verbal", "pain", "unresponsive"):
        assert score_consciousness(level) == 3


def test_total_score_uses_fahrenheit_input():
    # RR 22 (2) + SpO2 93 (2) + SBP 105 (1) + HR 115 (2) + 38.5 C (1) = 8
    vitals = {"resp_rate": 22, "o2sat": 93, "sbp": 105, "heart_rate": 115, "temperature": c_to_f(38.5)}
    result = calculate_news2(vitals)
    assert result.score == 8
    assert result.components == {"resp_rate": 2, "o2sat": 2, "sbp": 1, "heart_rate": 2, "temperature": 1}
    assert "room air assumed (supplemental O2 not recorded): 0 points" in result.assumptions


def test_missing_and_implausible_vitals_are_skipped():
    assert calculate_news2({}).score is None
    result = calculate_news2({"heart_rate": 80, "dbp": 879, "o2sat": 0})
    assert result.parameters_used == ["heart_rate"] and result.score == 0


def test_safety_net_rules():
    high = calculate_news2({"resp_rate": 26, "heart_rate": 80})          # single parameter = 3
    assert minimum_severity(high) == "High"
    medium = calculate_news2({"resp_rate": 22, "heart_rate": 115, "o2sat": 95})  # 2 + 2 + 1 = 5
    assert medium.score == 5 and minimum_severity(medium) == "Medium"
    normal = calculate_news2({"resp_rate": 16, "heart_rate": 80, "o2sat": 98})
    assert minimum_severity(normal) is None


def test_safety_net_raises_but_never_lowers():
    high = calculate_news2({"resp_rate": 30})
    raised = apply_safety_net("Low", high)
    assert raised["severity"] == "High" and raised["safety_override"] is True
    assert "single-parameter" in raised["override_reason"]
    kept = apply_safety_net("High", calculate_news2({"resp_rate": 16}))
    assert kept["severity"] == "High" and kept["safety_override"] is False
    medium = calculate_news2({"resp_rate": 22, "heart_rate": 115, "o2sat": 95})
    assert apply_safety_net("High", medium)["severity"] == "High"
    assert apply_safety_net("Low", medium)["severity"] == "Medium"
