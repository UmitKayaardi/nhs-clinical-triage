"""
NHS National Early Warning Score 2 (NEWS2) -- Agent 4's clinical safety net.

Scoring table: Royal College of Physicians (2017) National Early Warning
Score (NEWS) 2, chart 1. SpO2 uses Scale 1 (no hypercapnic respiratory
failure). Supplemental oxygen is not captured at intake, so the patient is
assumed to be on room air (0 points); this is a documented assumption.
Temperature is stored in Fahrenheit and converted to Celsius here.

Safety rules applied by the guardrail (they can only RAISE severity):
- NEWS2 >= 7, or any single parameter scoring 3  -> at least High
- NEWS2 5-6                                      -> at least Medium
The score is calculated from whichever parameters are available; the
parameters used are reported so a partial score is never mistaken for a
complete one.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.services.vitals import clean_vital, f_to_c

SEVERITY_ORDER = {"Low": 0, "Medium": 1, "High": 2}


def score_resp_rate(rr: float) -> int:
    if rr <= 8:
        return 3
    if rr <= 11:
        return 1
    if rr <= 20:
        return 0
    if rr <= 24:
        return 2
    return 3


def score_spo2_scale1(spo2: float) -> int:
    if spo2 <= 91:
        return 3
    if spo2 <= 93:
        return 2
    if spo2 <= 95:
        return 1
    return 0


def score_sbp(sbp: float) -> int:
    if sbp <= 90:
        return 3
    if sbp <= 100:
        return 2
    if sbp <= 110:
        return 1
    if sbp <= 219:
        return 0
    return 3


def score_pulse(hr: float) -> int:
    if hr <= 40:
        return 3
    if hr <= 50:
        return 1
    if hr <= 90:
        return 0
    if hr <= 110:
        return 1
    if hr <= 130:
        return 2
    return 3


def score_temperature_c(temp_c: float) -> int:
    if temp_c <= 35.0:
        return 3
    if temp_c <= 36.0:
        return 1
    if temp_c <= 38.0:
        return 0
    if temp_c <= 39.0:
        return 1
    return 2


def score_consciousness(level: Optional[str]) -> int:
    """Alert = 0; new confusion, Voice, Pain or Unresponsive = 3 (ACVPU)."""
    return 0 if (level or "").lower() in ("alert", "a") else 3


@dataclass
class News2Result:
    score: Optional[int]
    components: Dict[str, int] = field(default_factory=dict)
    parameters_used: List[str] = field(default_factory=list)
    any_single_three: bool = False
    assumptions: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "score": self.score,
            "components": self.components,
            "parameters_used": self.parameters_used,
            "any_single_three": self.any_single_three,
            "assumptions": self.assumptions,
        }


def calculate_news2(vitals: Optional[Dict], consciousness: Optional[str] = None) -> News2Result:
    """
    Args:
        vitals: keys temperature (deg F), heart_rate, resp_rate, o2sat, sbp
            (dbp is not part of NEWS2). Missing/implausible values are skipped.
        consciousness: "alert" | "verbal" | "pain" | "unresponsive" | "confusion" | None.
    """
    vitals = vitals or {}
    components: Dict[str, int] = {}

    rr = clean_vital("resp_rate", vitals.get("resp_rate"))
    if rr is not None:
        components["resp_rate"] = score_resp_rate(rr)
    spo2 = clean_vital("o2sat", vitals.get("o2sat"))
    if spo2 is not None:
        components["o2sat"] = score_spo2_scale1(spo2)
    sbp = clean_vital("sbp", vitals.get("sbp"))
    if sbp is not None:
        components["sbp"] = score_sbp(sbp)
    hr = clean_vital("heart_rate", vitals.get("heart_rate"))
    if hr is not None:
        components["heart_rate"] = score_pulse(hr)
    temp_f = clean_vital("temperature", vitals.get("temperature"))
    if temp_f is not None:
        components["temperature"] = score_temperature_c(f_to_c(temp_f))
    if consciousness:
        components["consciousness"] = score_consciousness(consciousness)

    if not components:
        return News2Result(score=None, assumptions=["no usable vital signs"])

    assumptions = ["room air assumed (supplemental O2 not recorded): 0 points", "SpO2 scale 1"]
    if "consciousness" not in components:
        assumptions.append("consciousness not recorded: not scored")
    return News2Result(
        score=sum(components.values()),
        components=components,
        parameters_used=sorted(components),
        any_single_three=any(v == 3 for v in components.values()),
        assumptions=assumptions,
    )


def minimum_severity(result: News2Result) -> Optional[str]:
    """The lowest severity the NEWS2 rules allow, or None when they impose no floor."""
    if result.score is None:
        return None
    if result.score >= 7 or result.any_single_three:
        return "High"
    if result.score >= 5:
        return "Medium"
    return None


def apply_safety_net(severity: str, result: News2Result) -> Dict:
    """
    Raises (never lowers) the severity according to the NEWS2 rules.

    Returns: {"severity", "safety_override", "override_reason", "news2_score"}
    """
    floor = minimum_severity(result)
    if floor and SEVERITY_ORDER[floor] > SEVERITY_ORDER.get(severity, 0):
        if result.score >= 7:
            why = f"NEWS2 {result.score} (>= 7)"
        elif result.any_single_three:
            params = [k for k, v in result.components.items() if v == 3]
            why = f"NEWS2 single-parameter score of 3 ({', '.join(params)})"
        else:
            why = f"NEWS2 {result.score} (5-6)"
        return {
            "severity": floor,
            "safety_override": True,
            "override_reason": f"{why}: severity raised from {severity} to {floor}",
            "news2_score": result.score,
        }
    return {"severity": severity, "safety_override": False, "override_reason": None, "news2_score": result.score}
