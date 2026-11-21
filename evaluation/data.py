"""
Dataset loaders for the offline evaluation.

Both loaders return one row per case with the SAME standard columns, so
every system (S0-S4, H) consumes identical inputs:

  case_id, group_id, label (Low/Medium/High), complaint, gender (M/F),
  age, temperature (deg F), heart_rate, resp_rate, o2sat, sbp, dbp, pain
  (0-10), consciousness (alert/verbal/pain/unresponsive), arrival_mode,
  injury (bool), dataset, plus dataset-specific extras (nurse_label for KTAS).

Columns that would leak the answer or happen after triage are never
returned as inputs (see KTAS_EXCLUDED_INPUTS).
"""

import re
import unicodedata
from typing import Tuple

import numpy as np
import pandas as pd

from app.models.mimic_models import map_acuity_to_severity
from app.services.vitals import c_to_f, clean_vital
from evaluation.common import DATA_DIR, KTAS_CSV, VITAL_KEYS, PreprocessLog, ktas_to_severity

KTAS_EXCLUDED_INPUTS = [
    "KTAS_RN", "KTAS_expert", "Error_group", "mistriage", "Diagnosis in ED", "Disposition",
    "Length of stay_min", "KTAS duration_min",
]

# The 19 chief complaints recorded in Korean, translated to English (fixed
# dictionary, documented in report_assets/preprocessing.md).
KOREAN_COMPLAINTS = {
    "구토": "vomiting",
    "다리 차가움": "cold leg",
    "명치 아픔": "epigastric pain",
    "목이 아픔": "neck pain",
    "변비가 있다": "constipation",
    "상복부": "upper abdominal pain",
    "설사": "diarrhea",
    "소변이 잘 안나옴": "difficulty urinating",
    "소변이 적다": "decreased urine output",
    "속이 거북함": "stomach discomfort",
    "손발이 저림": "numbness of hands and feet",
    "심계항진": "palpitations",
    "어지러움": "dizziness",
    "열상": "laceration",
    "우울증": "depression",
    "이상한 행동을 한다": "abnormal behavior",
    "턱이 빠진것 같다": "jaw dislocation",
    "피부병변": "skin lesion",
    "흉통": "chest pain",
}
# Abbreviations that the shared clinical normaliser does not know (documented expansion).
KTAS_ABBREVIATIONS = {r"(?<![A-Za-z])F/C(?![A-Za-z])": "fever chills", r"(?<![A-Za-z])C/S(?![A-Za-z])": "cough sputum"}
KTAS_UNMEASURABLE = "측불"  # Korean for "unmeasurable" in the vital-sign columns
MENTAL = {1: "alert", 2: "verbal", 3: "pain", 4: "unresponsive"}
ARRIVAL = {1: "walk-in", 2: "public ambulance", 3: "private car", 4: "private ambulance",
           5: "public transport/police", 6: "wheelchair", 7: "other"}
KTAS_SEX = {1: "F", 2: "M"}  # S2 coding sheet: 1 = Female, 2 = Male
KTAS_DISPOSITION = {1: "Discharge", 2: "Ward admission", 3: "ICU admission", 4: "AMA discharge",
                    5: "Transfer", 6: "Death", 7: "OP from ED"}


def _clean_pain(value) -> float:
    try:
        v = float(str(value).strip())
    except (TypeError, ValueError):
        return np.nan
    return v if 0 <= v <= 10 else np.nan


def load_mimic(log: PreprocessLog = None) -> pd.DataFrame:
    """MIMIC-IV-ED Demo v2.2: triage.csv + edstays.csv, one row per labelled stay."""
    log = log or PreprocessLog("MIMIC-IV-ED Demo")
    triage = pd.read_csv(DATA_DIR / "triage.csv")
    stays = pd.read_csv(DATA_DIR / "edstays.csv")
    log.add("load triage.csv", len(triage), len(triage), "one row per ED stay")
    df = triage.merge(stays[["stay_id", "gender", "race", "arrival_transport"]], on="stay_id", how="left")
    log.add("join edstays.csv on stay_id (gender, race, arrival)", len(triage), len(df), "")

    n = len(df)
    df = df.dropna(subset=["acuity"]).copy()
    log.add("drop stays without ESI acuity (unlabelled)", n, len(df), f"{n - len(df)} removed")
    df["label"] = [map_acuity_to_severity(a).value for a in df["acuity"]]
    log.add("map ESI acuity -> 3-class label (1-2 High, 3 Medium, 4-5 Low)", len(df), len(df),
            ", ".join(f"{k}: {v}" for k, v in df["label"].value_counts().items()))

    n = len(df)
    df["complaint"] = df["chiefcomplaint"].fillna("").astype(str).str.strip()
    df = df[df["complaint"] != ""].copy()
    log.add("drop empty chief complaints", n, len(df), "")

    rename = {"heartrate": "heart_rate", "resprate": "resp_rate"}
    df = df.rename(columns=rename)
    details = []
    for key in VITAL_KEYS:
        raw = pd.to_numeric(df[key], errors="coerce")
        celsius = raw.between(25, 50).sum() if key == "temperature" else 0
        df[key] = [clean_vital(key, v) for v in df[key]]
        df[key] = df[key].astype(float)
        dropped = int(raw.notna().sum() - df[key].notna().sum())
        details.append(f"{key}: {int(raw.isna().sum())} missing, {dropped} implausible -> NaN"
                       + (f", {celsius} Celsius values converted to F" if celsius else ""))
    log.add("vital signs: numeric coercion, plausibility ranges, unit fix", len(df), len(df), "; ".join(details))

    raw_pain = df["pain"].copy()
    df["pain"] = [_clean_pain(v) for v in raw_pain]
    log.add("pain: keep numeric 0-10, others (e.g. 'unable', 'UA', '13') -> NaN", len(df), len(df),
            f"{int(raw_pain.notna().sum() - df['pain'].notna().sum())} non-numeric/out-of-range -> NaN")

    df["case_id"] = df["stay_id"].astype(int).astype(str)
    df["stay_id"] = df["stay_id"].astype(int)
    df["group_id"] = df["subject_id"].astype(int)
    df["age"] = np.nan                 # not available in the ED demo tables
    df["consciousness"] = None         # not recorded at MIMIC triage
    df["arrival_mode"] = df["arrival_transport"].fillna("").str.lower().replace("", None)
    df["injury"] = None
    df["dataset"] = "mimic"
    cols = ["case_id", "stay_id", "group_id", "label", "complaint", "gender", "age", *VITAL_KEYS, "pain",
            "consciousness", "arrival_mode", "injury", "race", "dataset"]
    out = df[cols].reset_index(drop=True)
    log.add("final MIMIC evaluation set", len(out), len(out),
            f"{out['group_id'].nunique()} patients; " + ", ".join(f"{k}: {v}" for k, v in out["label"].value_counts().items()))
    return out


def _translate_complaint(text: str) -> Tuple[str, str]:
    """Returns (clean_text, action) where action is 'translated' | 'normalised' | 'kept' | 'unreadable'."""
    raw = "" if text is None or (isinstance(text, float) and np.isnan(text)) else str(text).strip()
    if raw in KOREAN_COMPLAINTS:
        return KOREAN_COMPLAINTS[raw], "translated"
    folded = unicodedata.normalize("NFKD", raw)
    folded = folded.replace("Α", "A")  # Greek capital alpha typed instead of Latin A
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    for pattern, expansion in KTAS_ABBREVIATIONS.items():
        ascii_text = re.sub(pattern, expansion, ascii_text)
    ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
    if not re.search(r"[A-Za-z]", ascii_text):
        return "", "unreadable"
    return ascii_text, ("normalised" if ascii_text != raw else "kept")


def _ktas_numeric(series: pd.Series) -> Tuple[pd.Series, int, int]:
    s = series.astype(str).str.strip()
    unmeasurable = int((s == KTAS_UNMEASURABLE).sum())
    commas = int(s.str.contains(r"^\d+,\d+$", regex=True).sum())
    s = s.str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce"), unmeasurable, commas


def load_ktas(log: PreprocessLog = None) -> pd.DataFrame:
    """KTAS (Moon et al., 2019): 1,267 adult ED records; ground truth KTAS_expert, nurse baseline KTAS_RN."""
    log = log or PreprocessLog("KTAS (Moon et al., 2019)")
    raw = pd.read_csv(KTAS_CSV, encoding="utf-8")
    log.add("load ktas_raw.csv (from PLoS S1 XLSX)", len(raw), len(raw), f"{raw.shape[1]} columns")
    df = raw.copy()
    df["row_id"] = np.arange(len(df))

    actions = [_translate_complaint(v) for v in df["Chief_complain"]]
    df["complaint"] = [a[0] for a in actions]
    counts = pd.Series([a[1] for a in actions]).value_counts().to_dict()
    log.add("chief complaint: strip, Unicode->ASCII, translate Korean (fixed dictionary), expand F/C and C/S", len(df), len(df),
            ", ".join(f"{k}: {v}" for k, v in counts.items()))
    n = len(df)
    df = df[df["complaint"] != ""].copy()
    log.add("drop unreadable complaints", n, len(df), f"{n - len(df)} removed")

    detail = []
    vital_map = {"SBP": "sbp", "DBP": "dbp", "HR": "heart_rate", "RR": "resp_rate", "BT": "temperature_c",
                 "Saturation": "o2sat"}
    for src, dst in vital_map.items():
        values, unmeasurable, commas = _ktas_numeric(df[src])
        df[dst] = values
        detail.append(f"{src}: {unmeasurable} '{KTAS_UNMEASURABLE}' (unmeasurable), {commas} comma decimals, "
                      f"{int(values.isna().sum())} missing after coercion")
    log.add("vital signs: unmeasurable marker -> NaN, comma decimal -> dot, numeric coercion", len(df), len(df),
            "; ".join(detail))
    df["temperature"] = [c_to_f(v) if pd.notna(v) else np.nan for v in df["temperature_c"]]
    log.add("body temperature deg C -> deg F (MIMIC unit)", len(df), len(df), "F = C x 9/5 + 32")
    plaus = []
    for key in VITAL_KEYS:
        before = int(df[key].notna().sum())
        df[key] = [clean_vital(key, v) for v in df[key]]
        df[key] = df[key].astype(float)
        plaus.append(f"{key}: {before - int(df[key].notna().sum())}")
    log.add("plausibility ranges (implausible -> NaN)", len(df), len(df), "; ".join(plaus))

    df["pain"] = np.where(df["Pain"] == 0, 0.0, df["NRS_pain"])
    df["pain"] = [_clean_pain(v) for v in df["pain"]]
    log.add("pain: Pain flag 0 (no pain) -> NRS 0; NRS kept 0-10", len(df), len(df),
            f"{int(df['pain'].isna().sum())} missing after rule")

    df["gender"] = df["Sex"].map(KTAS_SEX)
    df["consciousness"] = df["Mental"].map(MENTAL)
    df["arrival_mode"] = df["Arrival mode"].map(ARRIVAL)
    df["injury"] = df["Injury"] == 2
    df["age"] = df["Age"].astype(float)
    log.add("encode Sex (1 F / 2 M), Mental (AVPU), Arrival mode and Injury as text", len(df), len(df),
            "one-hot encoded later for the ML baselines")

    df["label"] = df["KTAS_expert"].map(ktas_to_severity)
    df["nurse_label"] = df["KTAS_RN"].map(ktas_to_severity)
    log.add("labels: KTAS_expert -> 3-class ground truth; KTAS_RN -> nurse baseline (H)", len(df), len(df),
            "truth " + ", ".join(f"{k}: {v}" for k, v in df["label"].value_counts().items())
            + "; nurse " + ", ".join(f"{k}: {v}" for k, v in df["nurse_label"].value_counts().items()))

    df["case_id"] = "ktas-" + df["row_id"].astype(str)
    df["stay_id"] = df["row_id"].astype(int)
    df["group_id"] = df["row_id"].astype(int)
    df["site"] = df["Group"].map({1: "local ED", 2: "regional ED"})
    df["diagnosis_ed"] = df["Diagnosis in ED"].fillna("").astype(str)          # KB evidence only, never an input
    df["disposition"] = df["Disposition"].map(KTAS_DISPOSITION)               # KB evidence only, never an input
    df["dataset"] = "ktas"
    cols = ["case_id", "stay_id", "group_id", "row_id", "label", "nurse_label", "complaint", "gender", "age",
            *VITAL_KEYS, "pain", "consciousness", "arrival_mode", "injury", "site", "diagnosis_ed",
            "disposition", "dataset"]
    out = df[cols].reset_index(drop=True)
    log.add("final KTAS evaluation set", len(out), len(out),
            "excluded as inputs: " + ", ".join(KTAS_EXCLUDED_INPUTS))
    return out
