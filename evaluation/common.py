"""Shared constants and small helpers for the offline evaluation."""

import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "evaluation"
SPLITS_DIR = EVAL_DIR / "splits"
CACHE_DIR = EVAL_DIR / "cache"
RESULTS_DIR = EVAL_DIR / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
REPORT_ASSETS = ROOT / "report_assets"
DATA_DIR = ROOT / "data"
KTAS_CSV = DATA_DIR / "external" / "ktas" / "ktas_raw.csv"
MIMIC_DB = ROOT / "triage_data.db"

SEED = 42
LABELS = ["Low", "Medium", "High"]           # ordinal order, least to most urgent
ORDINAL = {label: i for i, label in enumerate(LABELS)}
VITAL_KEYS = ["temperature", "heart_rate", "resp_rate", "o2sat", "sbp", "dbp"]


def ktas_to_severity(level: int) -> str:
    """KTAS 1-2 -> High, 3 -> Medium, 4-5 -> Low (same 3-tier mapping as ESI in the app)."""
    level = int(level)
    if level in (1, 2):
        return "High"
    if level == 3:
        return "Medium"
    if level in (4, 5):
        return "Low"
    raise ValueError(f"Unmapped KTAS level: {level}")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=_default), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _default(obj):
    import numpy as np

    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"Not JSON serialisable: {type(obj)}")


class PreprocessLog:
    """Collects every cleaning/encoding step with row counts (written to report_assets/preprocessing.md)."""

    def __init__(self, dataset: str):
        self.dataset = dataset
        self.steps: List[Dict[str, Any]] = []

    def add(self, step: str, rows_before: int, rows_after: int, detail: str = "") -> None:
        self.steps.append({"step": step, "rows_before": int(rows_before), "rows_after": int(rows_after),
                           "detail": detail})

    def as_dict(self) -> Dict[str, Any]:
        return {"dataset": self.dataset, "steps": self.steps}
