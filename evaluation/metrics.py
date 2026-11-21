"""
Metric functions for 3-class ordinal triage (Low < Medium < High).

under-triage: predicted level LOWER (less urgent) than the true level
over-triage:  predicted level HIGHER (more urgent) than the true level
"""

from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy import stats
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)

from evaluation.common import LABELS, ORDINAL, SEED


def _ord(labels: Sequence[str]) -> np.ndarray:
    return np.array([ORDINAL[label] for label in labels])


def under_over_triage(y_true: Sequence[str], y_pred: Sequence[str]) -> Dict[str, float]:
    t, p = _ord(y_true), _ord(y_pred)
    n = len(t)
    return {
        "under_triage_rate": float(np.mean(p < t)) if n else float("nan"),
        "over_triage_rate": float(np.mean(p > t)) if n else float("nan"),
        "under_triage_n": int(np.sum(p < t)),
        "over_triage_n": int(np.sum(p > t)),
    }


def classification_metrics(y_true: Sequence[str], y_pred: Sequence[str],
                           proba: Optional[np.ndarray] = None) -> Dict:
    """All point metrics for one system on one dataset. `proba` columns follow LABELS order."""
    y_true, y_pred = list(y_true), list(y_pred)
    present = [label for label in LABELS if label in y_true]
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    row_sums = cm.sum(axis=1, keepdims=True)
    cm_norm = np.divide(cm, row_sums, out=np.zeros_like(cm, dtype=float), where=row_sums > 0)
    out = {
        "n": len(y_true),
        "accuracy": accuracy_score(y_true, y_pred),
        "balanced_accuracy": balanced_accuracy_score(y_true, y_pred),
        # Macro over the classes present in the ground truth (avoids a 0 for an absent class).
        "precision_macro": float(np.mean([p[LABELS.index(c)] for c in present])),
        "recall_macro": float(np.mean([r[LABELS.index(c)] for c in present])),
        "f1_macro": f1_score(y_true, y_pred, labels=present, average="macro", zero_division=0),
        "precision_weighted": float(np.average(p, weights=s)) if s.sum() else 0.0,
        "recall_weighted": float(np.average(r, weights=s)) if s.sum() else 0.0,
        "f1_weighted": f1_score(y_true, y_pred, labels=LABELS, average="weighted", zero_division=0),
        "per_class": {
            label: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
            for i, label in enumerate(LABELS)
        },
        "kappa_linear": _kappa(y_true, y_pred),
        "high_recall": float(r[LABELS.index("High")]),
        "confusion_matrix": cm.tolist(),
        "confusion_matrix_normalised": np.round(cm_norm, 4).tolist(),
        "labels": LABELS,
        "pred_distribution": {label: int(sum(1 for y in y_pred if y == label)) for label in LABELS},
    }
    out.update(under_over_triage(y_true, y_pred))
    if proba is not None:
        out["roc_auc_macro_ovr"] = roc_auc_ovr(y_true, proba)
    small = [label for label in LABELS if 0 < s[LABELS.index(label)] < 5]
    if small or len(present) < len(LABELS):
        out["warning"] = (f"classes with <5 examples: {small}; classes absent from ground truth: "
                          f"{[c for c in LABELS if c not in present]} -- per-class metrics for these are unreliable")
    return {k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in out.items()}


def _kappa(y_true, y_pred) -> float:
    if len(set(y_true) | set(y_pred)) < 2:
        return float("nan")
    return float(cohen_kappa_score(_ord(y_true), _ord(y_pred), weights="linear", labels=[0, 1, 2]))


def roc_auc_ovr(y_true: Sequence[str], proba: np.ndarray) -> Optional[float]:
    """Macro one-vs-rest AUC over the classes that are present (needs >= 2 classes)."""
    y = np.array(y_true)
    aucs = []
    for i, label in enumerate(LABELS):
        positives = y == label
        if positives.sum() == 0 or positives.all():
            continue
        aucs.append(roc_auc_score(positives.astype(int), proba[:, i]))
    return float(np.mean(aucs)) if aucs else None


def bootstrap_ci(y_true: Sequence[str], y_pred: Sequence[str], n_boot: int = 1000, seed: int = SEED,
                 alpha: float = 0.05) -> Dict[str, Dict[str, float]]:
    """Percentile bootstrap CIs (case resampling) for accuracy, macro-F1 and under-triage rate."""
    t, p = np.array(y_true), np.array(y_pred)
    n = len(t)
    rng = np.random.default_rng(seed)
    acc, f1, under = [], [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        tt, pp = t[idx], p[idx]
        acc.append(np.mean(tt == pp))
        present = [c for c in LABELS if c in tt]
        f1.append(f1_score(tt, pp, labels=present, average="macro", zero_division=0))
        under.append(np.mean(_ord(pp) < _ord(tt)))
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)

    def ci(values):
        return {"low": float(np.percentile(values, lo)), "high": float(np.percentile(values, hi))}

    return {"accuracy": ci(acc), "f1_macro": ci(f1), "under_triage_rate": ci(under), "n_boot": n_boot}


def mcnemar(y_true: Sequence[str], pred_a: Sequence[str], pred_b: Sequence[str]) -> Dict:
    """Exact McNemar test (binomial on discordant pairs) comparing two systems on the same cases."""
    t, a, b = np.array(y_true), np.array(pred_a), np.array(pred_b)
    a_ok, b_ok = a == t, b == t
    n01 = int(np.sum(a_ok & ~b_ok))   # A right, B wrong
    n10 = int(np.sum(~a_ok & b_ok))   # A wrong, B right
    n_disc = n01 + n10
    p = float(stats.binomtest(n01, n_disc, 0.5).pvalue) if n_disc else 1.0
    return {"a_correct_b_wrong": n01, "a_wrong_b_correct": n10, "discordant": n_disc, "p_value_exact": p,
            "n": int(len(t))}


def summarise_cv(fold_scores: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    out = {}
    for key in fold_scores[0]:
        vals = np.array([f[key] for f in fold_scores], dtype=float)
        out[key] = {"mean": float(np.nanmean(vals)), "std": float(np.nanstd(vals, ddof=1)) if len(vals) > 1 else 0.0,
                    "folds": [float(v) for v in vals]}
    return out


def retrieval_quality(true_label: str, neighbour_labels: List[str], neighbour_scores: List[float],
                      k: int) -> Dict[str, float]:
    top = neighbour_labels[:k]
    return {
        "precision_at_k": (sum(1 for x in top if x == true_label) / len(top)) if top else 0.0,
        "top1_similarity": float(neighbour_scores[0]) if neighbour_scores else 0.0,
    }
