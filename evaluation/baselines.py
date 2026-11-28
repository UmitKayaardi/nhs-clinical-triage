"""
LLM-free systems: S0 majority class, S1 retrieval-only (Agent 2), S2a
Logistic Regression, S2b Random Forest -- plus knowledge-base builders
used by S1 and the full system (S4).

Knowledge bases (leakage control):
- MIMIC: the production retrieval code, restricted to TRAIN stay IDs, built
  from the committed triage_data.db opened read-only.
- KTAS: records built from KTAS-train rows (complaint, expert label,
  vitals, ED diagnosis and disposition as historical evidence).
"""

import itertools
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import retrieval_service as rs
from evaluation.common import LABELS, MIMIC_DB, SEED, VITAL_KEYS
from evaluation.metrics import classification_metrics

K_GRID = [3, 5, 7, 10]
WEIGHT_GRID = [
    {"complaint": 1.0, "diagnosis": d, "vitals": v, "medication": m}
    for d, v, m in itertools.product([0.3, 0.7, 1.0], [0.25, 0.5, 1.0], [0.0, 0.3])
]
DEFAULT_WEIGHTS = {"complaint": 1.0, "diagnosis": 0.7, "vitals": 0.5, "medication": 0.3}

_ro_session = None


def readonly_mimic_session():
    """Session on the committed SQLite DB opened read-only (evaluation never writes to it)."""
    global _ro_session
    if _ro_session is None:
        uri = f"sqlite:///file:{MIMIC_DB.as_posix()}?mode=ro&uri=true"
        engine = create_engine(uri, connect_args={"check_same_thread": False})
        _ro_session = sessionmaker(bind=engine)()
    return _ro_session


def mimic_index(stay_ids: Iterable[int]):
    records = rs.records_from_db(readonly_mimic_session(), [int(s) for s in stay_ids])
    return rs.build_index(records)


def ktas_records(df: pd.DataFrame) -> List:
    """KTAS rows as knowledge-base records (same builder as the live KTAS knowledge base)."""
    return [rs.ktas_record(int(row.stay_id), row.complaint, row.label, row.diagnosis_ed or None,
                           {k: (None if pd.isna(getattr(row, k)) else float(getattr(row, k))) for k in VITAL_KEYS},
                           row.disposition if isinstance(row.disposition, str) else None)
            for row in df.itertuples()]


def ktas_index(train_df: pd.DataFrame):
    return rs.build_index(ktas_records(train_df))


def combined_index(ktas_train_df: pd.DataFrame):
    """Multi-source evaluation KB: all MIMIC-IV-ED stays + the given KTAS records (KTAS train only)."""
    return rs.build_index(rs.records_from_db(readonly_mimic_session()) + ktas_records(ktas_train_df))


def build_kb(dataset: str, kb_df: pd.DataFrame):
    return mimic_index(kb_df["stay_id"]) if dataset == "mimic" else ktas_index(kb_df)


def case_vitals(row) -> Dict[str, Optional[float]]:
    return {k: (None if pd.isna(row[k]) else float(row[k])) for k in VITAL_KEYS}


# ---------------------------------------------------------------- S0
def majority_predict(train_labels: Iterable[str], n: int) -> Tuple[List[str], np.ndarray]:
    counts = pd.Series(list(train_labels)).value_counts()
    label = counts.index[0]
    prior = np.array([counts.get(c, 0) / counts.sum() for c in LABELS])
    return [label] * n, np.tile(prior, (n, 1))


# ---------------------------------------------------------------- S1
def retrieve_all(df: pd.DataFrame, index, weights: Dict[str, float], k_max: int = 10) -> List[List[rs.SimilarCase]]:
    return [rs.find_similar_cases(None, row["complaint"], case_vitals(row), limit=k_max, index=index, weights=weights)
            for _, row in df.iterrows()]


def vote(cases: List[rs.SimilarCase], k: int, prior: np.ndarray) -> Tuple[str, np.ndarray]:
    """Similarity-weighted vote of the top-k neighbours; falls back to the KB class prior when nothing is found."""
    top = cases[:k]
    if not top:
        proba = prior.copy()
    else:
        w = np.zeros(len(LABELS))
        for c in top:
            if c.severity in LABELS:
                w[LABELS.index(c.severity)] += c.similarity_score
        proba = w / w.sum() if w.sum() > 0 else prior.copy()
    # Ties broken towards the more urgent class (safer).
    best = max(range(len(LABELS)), key=lambda i: (round(proba[i], 9), i))
    return LABELS[best], proba


def s1_predict(retrieved: List[List[rs.SimilarCase]], k: int, prior: np.ndarray) -> Tuple[List[str], np.ndarray]:
    preds, probas = [], []
    for cases in retrieved:
        p, pr = vote(cases, k, prior)
        preds.append(p)
        probas.append(pr)
    return preds, np.vstack(probas)


def prior_of(labels: Iterable[str]) -> np.ndarray:
    s = pd.Series(list(labels)).value_counts()
    return np.array([s.get(c, 0) / s.sum() for c in LABELS])


def tune_s1(dataset: str, train: pd.DataFrame, val: pd.DataFrame) -> Dict:
    """Grid over retrieval weights x k on the validation split; selects by macro-F1 (ties: accuracy, smaller k)."""
    index = build_kb(dataset, train)
    prior = prior_of(train["label"])
    rows = []
    for weights in WEIGHT_GRID:
        retrieved = retrieve_all(val, index, weights, max(K_GRID))
        for k in K_GRID:
            preds, _ = s1_predict(retrieved, k, prior)
            m = classification_metrics(val["label"], preds)
            rows.append({"weights": weights, "k": k, "f1_macro": m["f1_macro"], "accuracy": m["accuracy"],
                         "under_triage_rate": m["under_triage_rate"]})
    rows.sort(key=lambda r: (-r["f1_macro"], -r["accuracy"], r["k"]))
    return {"best": rows[0], "grid": rows}


# ---------------------------------------------------------------- S2
def _feature_frame(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    out = pd.DataFrame({"text": df["complaint"].fillna("")})
    numeric = VITAL_KEYS + ["pain"] + (["age"] if dataset == "ktas" else [])
    for col in numeric:
        out[col] = df[col].astype(float)
    out["gender"] = df["gender"].fillna("unknown").astype(str)
    if dataset == "ktas":
        out["consciousness"] = df["consciousness"].fillna("unknown").astype(str)
        out["arrival_mode"] = df["arrival_mode"].fillna("unknown").astype(str)
        out["injury"] = df["injury"].map({True: "injury", False: "non-injury"}).fillna("unknown")
    return out


def _preprocessor(dataset: str) -> ColumnTransformer:
    numeric = VITAL_KEYS + ["pain"] + (["age"] if dataset == "ktas" else [])
    categorical = ["gender"] + (["consciousness", "arrival_mode", "injury"] if dataset == "ktas" else [])
    return ColumnTransformer([
        ("text", TfidfVectorizer(tokenizer=rs._normalise, lowercase=False, token_pattern=None), "text"),
        ("num", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                          ("scale", StandardScaler())]), numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
    ])


LR_GRID = [{"C": c} for c in (0.1, 0.3, 1.0, 3.0, 10.0)]
RF_GRID = [{"n_estimators": n, "max_depth": d, "min_samples_leaf": leaf}
           for n, d, leaf in itertools.product([200, 500], [None, 5, 10], [1, 3])]


def make_model(kind: str, dataset: str, params: Dict) -> Pipeline:
    if kind == "lr":
        clf = LogisticRegression(class_weight="balanced", max_iter=5000, random_state=SEED, **params)
    else:
        clf = RandomForestClassifier(class_weight="balanced", random_state=SEED, n_jobs=-1, **params)
    return Pipeline([("features", _preprocessor(dataset)), ("clf", clf)])


def ml_fit_predict(kind: str, dataset: str, params: Dict, train: pd.DataFrame, test: pd.DataFrame):
    model = make_model(kind, dataset, params)
    model.fit(_feature_frame(train, dataset), train["label"])
    proba_raw = model.predict_proba(_feature_frame(test, dataset))
    classes = list(model.classes_)
    proba = np.zeros((len(test), len(LABELS)))
    for i, c in enumerate(classes):
        proba[:, LABELS.index(c)] = proba_raw[:, i]
    preds = [LABELS[i] for i in proba.argmax(axis=1)]
    return preds, proba, model


def tune_ml(kind: str, dataset: str, train: pd.DataFrame, val: pd.DataFrame) -> Dict:
    grid = LR_GRID if kind == "lr" else RF_GRID
    rows = []
    for params in grid:
        preds, _, _ = ml_fit_predict(kind, dataset, params, train, val)
        m = classification_metrics(val["label"], preds)
        rows.append({"params": params, "f1_macro": m["f1_macro"], "accuracy": m["accuracy"]})
    rows.sort(key=lambda r: (-r["f1_macro"], -r["accuracy"]))
    return {"best": rows[0], "grid": rows}


def feature_names(model: Pipeline) -> List[str]:
    try:
        return list(model.named_steps["features"].get_feature_names_out())
    except Exception:
        return []
