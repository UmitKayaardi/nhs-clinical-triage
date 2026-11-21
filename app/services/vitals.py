"""
Shared vital-sign helpers (used by Agent 4's NEWS2 safety net and the
offline evaluation).

- Units: the system stores temperature in degrees Fahrenheit, as MIMIC-IV-ED
  does. KTAS records body temperature in Celsius and is converted on load.
- Plausibility: values outside physiologically possible ranges are treated
  as missing (e.g. MIMIC has a diastolic pressure of 879 and pain scores of
  13). A temperature below 50 in a Fahrenheit field is a Celsius value
  entered in the wrong unit and is converted.
"""

import math
from typing import Dict, Optional

# Inclusive plausible ranges; anything outside is treated as missing.
PLAUSIBLE_RANGES: Dict[str, tuple] = {
    "temperature": (85.0, 112.0),   # deg F
    "heart_rate": (20.0, 300.0),
    "resp_rate": (3.0, 80.0),
    "o2sat": (50.0, 100.0),
    "sbp": (40.0, 300.0),
    "dbp": (20.0, 200.0),
    "pain": (0.0, 10.0),
}


def c_to_f(celsius: Optional[float]) -> Optional[float]:
    if celsius is None:
        return None
    return round(celsius * 9.0 / 5.0 + 32.0, 1)


def f_to_c(fahrenheit: Optional[float]) -> Optional[float]:
    if fahrenheit is None:
        return None
    return round((fahrenheit - 32.0) * 5.0 / 9.0, 1)


def _as_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if not value:
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def clean_vital(name: str, value) -> Optional[float]:
    """Returns a plausible float for one vital sign, or None."""
    v = _as_float(value)
    if v is None:
        return None
    if name == "temperature" and 25.0 <= v < 50.0:
        v = c_to_f(v)  # Celsius entered in a Fahrenheit field
    low, high = PLAUSIBLE_RANGES.get(name, (-math.inf, math.inf))
    return v if low <= v <= high else None


def clean_vitals(vitals: Optional[Dict]) -> Dict[str, Optional[float]]:
    """Cleans every known vital in a dict; unknown keys are passed through unchanged."""
    out: Dict[str, Optional[float]] = {}
    for key, value in (vitals or {}).items():
        out[key] = clean_vital(key, value) if key in PLAUSIBLE_RANGES else value
    return out
