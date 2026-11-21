"""
Reproducible train / validation / test splits (seed 42).

- MIMIC: patient-grouped, stratified 70/15/15. Whole patients are assigned
  to one split (no subject_id appears in two splits). Because one patient
  has 23 of the 207 labelled stays, the assignment is chosen from 2,000
  seeded random group orders: each order is filled greedily into the split
  furthest below its target size, and the order with the smallest combined
  size + class-proportion error is kept.
- KTAS: stratified 70/15/15 on the 3-class expert label
  (sklearn train_test_split twice).
"""

from collections import Counter
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from evaluation.common import LABELS, SEED, SPLITS_DIR, read_json, write_json

RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}


def _assignment_cost(df: pd.DataFrame, assign: Dict[int, str]) -> float:
    split = df["group_id"].map(assign)
    n = len(df)
    overall = df["label"].value_counts(normalize=True)
    cost = 0.0
    for name, ratio in RATIOS.items():
        part = df[split == name]
        cost += abs(len(part) / n - ratio) * 3.0
        if len(part) == 0:
            return float("inf")
        props = part["label"].value_counts(normalize=True)
        for label in ("High", "Medium"):  # Low has 2 cases in total; it cannot be balanced
            cost += abs(props.get(label, 0.0) - overall.get(label, 0.0))
    return cost


def grouped_stratified_split(df: pd.DataFrame, n_orders: int = 2000, seed: int = SEED) -> Dict[str, List[str]]:
    rng = np.random.default_rng(seed)
    group_sizes = df.groupby("group_id").size()
    groups = group_sizes.index.to_numpy()
    n = len(df)
    best, best_cost = None, float("inf")
    for _ in range(n_orders):
        order = rng.permutation(groups)
        # Largest groups first keeps the greedy fill close to the targets.
        order = sorted(order, key=lambda g: -group_sizes[g] if group_sizes[g] > 8 else 0)
        filled = {k: 0 for k in RATIOS}
        assign = {}
        for g in order:
            deficit = {k: RATIOS[k] * n - filled[k] for k in RATIOS}
            target = max(deficit, key=deficit.get)
            assign[g] = target
            filled[target] += group_sizes[g]
        cost = _assignment_cost(df, assign)
        if cost < best_cost:
            best, best_cost = assign, cost
    split = df["group_id"].map(best)
    return {name: sorted(df.loc[split == name, "case_id"].tolist()) for name in RATIOS}


def stratified_split(df: pd.DataFrame, seed: int = SEED) -> Dict[str, List[str]]:
    train, rest = train_test_split(df, test_size=0.30, stratify=df["label"], random_state=seed)
    val, test = train_test_split(rest, test_size=0.50, stratify=rest["label"], random_state=seed)
    return {"train": sorted(train["case_id"]), "validation": sorted(val["case_id"]), "test": sorted(test["case_id"])}


def describe(df: pd.DataFrame, split: Dict[str, List[str]]) -> Dict:
    out = {}
    for name, ids in split.items():
        part = df[df["case_id"].isin(ids)]
        out[name] = {
            "n_cases": len(part),
            "n_groups": int(part["group_id"].nunique()),
            "share": round(len(part) / len(df), 3),
            "class_counts": {label: int((part["label"] == label).sum()) for label in LABELS},
        }
    return out


def make_or_load(df: pd.DataFrame, dataset: str, force: bool = False) -> Dict[str, List[str]]:
    path = SPLITS_DIR / f"{dataset}_split.json"
    if path.exists() and not force:
        return read_json(path)["splits"]
    split = grouped_stratified_split(df) if dataset == "mimic" else stratified_split(df)
    # Sanity: disjoint and complete; for MIMIC no patient in two splits.
    all_ids = [i for ids in split.values() for i in ids]
    assert len(all_ids) == len(set(all_ids)) == len(df)
    if dataset == "mimic":
        groups = {name: set(df[df["case_id"].isin(ids)]["group_id"]) for name, ids in split.items()}
        assert not (groups["train"] & groups["validation"]) and not (groups["train"] & groups["test"]) \
            and not (groups["validation"] & groups["test"])
    write_json(path, {
        "dataset": dataset,
        "seed": SEED,
        "method": "patient-grouped stratified 70/15/15" if dataset == "mimic" else "stratified 70/15/15",
        "id_column": "stay_id" if dataset == "mimic" else "row index of ktas_raw.csv (case_id = ktas-<row>)",
        "summary": describe(df, split),
        "splits": split,
    })
    return split


def subset(df: pd.DataFrame, ids: List[str]) -> pd.DataFrame:
    return df[df["case_id"].isin(set(ids))].reset_index(drop=True)


def ktas_llm_sample(test_df: pd.DataFrame, per_class: int = 40, seed: int = SEED) -> List[str]:
    """Stratified sample of the KTAS test split for the LLM systems (default 40 per class = 120)."""
    ids = []
    for label in LABELS:
        part = test_df[test_df["label"] == label].sort_values("case_id")
        k = min(per_class, len(part))
        ids += part.sample(n=k, random_state=seed)["case_id"].tolist()
    return sorted(ids)


def class_counts(labels) -> Dict[str, int]:
    c = Counter(labels)
    return {label: int(c.get(label, 0)) for label in LABELS}
