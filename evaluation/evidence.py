"""
WP2 -- choosing LOW_EVIDENCE_THRESHOLD (LLM-free, test split never used).

Signal: top-1 similarity of the production retrieval (default weights, k=5).
Outcome proxy: correctness of the similarity-weighted neighbour vote.
Candidates: T in 0.300, 0.325, ..., 0.700 with 10-40 % of cases flagged.
Rule: pick T with the largest accuracy drop (accuracy of unflagged cases minus
accuracy of flagged cases).

Two tables are produced:
- validation split only (31 stays; reported for transparency), and
- out-of-fold predictions on the development set (train + validation,
  5-fold patient-grouped CV, 176 stays) -- used for the choice, because 31
  cases give unstable estimates. The test split is not touched.
"""

from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from evaluation.baselines import DEFAULT_WEIGHTS, build_kb, prior_of, retrieve_all, s1_predict
from evaluation.common import SEED

CANDIDATES = [round(x, 3) for x in np.arange(0.300, 0.7001, 0.025)]
MIN_FLAG_RATE, MAX_FLAG_RATE = 0.10, 0.40


def _table(top: np.ndarray, correct: np.ndarray) -> List[Dict]:
    rows = []
    for t in CANDIDATES:
        flagged = top < t
        rows.append({
            "threshold": t,
            "n_flagged": int(flagged.sum()),
            "flag_rate": round(float(flagged.mean()), 3),
            "acc_flagged": round(float(correct[flagged].mean()), 3) if flagged.any() else None,
            "acc_unflagged": round(float(correct[~flagged].mean()), 3) if (~flagged).any() else None,
        })
    for r in rows:
        r["accuracy_drop"] = (round(r["acc_unflagged"] - r["acc_flagged"], 3)
                              if r["acc_flagged"] is not None and r["acc_unflagged"] is not None else None)
    return rows


def _choose(rows: List[Dict]) -> Dict:
    eligible = [r for r in rows if MIN_FLAG_RATE <= r["flag_rate"] <= MAX_FLAG_RATE and r["accuracy_drop"] is not None]
    return max(eligible, key=lambda r: (r["accuracy_drop"], -r["threshold"])) if eligible else None


def _signals(train: pd.DataFrame, test: pd.DataFrame):
    index = build_kb("mimic", train)
    retrieved = retrieve_all(test, index, DEFAULT_WEIGHTS, 5)
    preds, _ = s1_predict(retrieved, 5, prior_of(train["label"]))
    top = np.array([c[0].similarity_score if c else 0.0 for c in retrieved])
    return top, np.array(preds) == test["label"].to_numpy()


def tune_threshold(train: pd.DataFrame, val: pd.DataFrame) -> Dict:
    top_v, ok_v = _signals(train, val)
    val_rows = _table(top_v, ok_v)

    dev = pd.concat([train, val], ignore_index=True)
    top = np.zeros(len(dev))
    ok = np.zeros(len(dev), dtype=bool)
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    for tr_idx, te_idx in cv.split(dev, dev["label"], dev["group_id"]):
        t, o = _signals(dev.iloc[tr_idx], dev.iloc[te_idx])
        top[te_idx], ok[te_idx] = t, o
    dev_rows = _table(top, ok)
    chosen = _choose(dev_rows)
    return {
        "rule": "largest accuracy drop (unflagged - flagged) with 10-40% of cases flagged",
        "signal": "top-1 similarity, production retrieval weights, k=5",
        "chosen_threshold": chosen["threshold"] if chosen else None,
        "chosen_row": chosen,
        "development_oof_table": dev_rows,
        "validation_only_table": val_rows,
        "validation_only_choice": _choose(val_rows),
        "n_validation": len(val),
        "n_development": len(dev),
    }
