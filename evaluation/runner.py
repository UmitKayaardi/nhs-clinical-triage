"""
Orchestrates the evaluation stages used by scripts/evaluate.py.

MIMIC protocol v2 (see evaluation/splits.py::make_mimic_v2):
  development  old validation + old test splits (62 stays). Prompt v1 -> v2 was developed here and all
               LLM-free tuning uses it. Development LLM jobs reuse the cached calls (KB = old train split).
  test         NEW held-out split (31 stays, 9 patients never used as an LLM query). Evaluated ONCE with the
               frozen configuration (evaluation/frozen_config.json). KB = remaining training patients.
KTAS is the MAIN evaluation (since 2026-11-22) with the same frozen configuration: full test split (191 cases),
multi-source knowledge base = all MIMIC-IV-ED stays + KTAS training split only (886). The secondary KB = MIMIC-only
job keeps its 117-case stratified sample (test-sample) and is extended to the other 74 test cases (test-rest) only
when the daily budget allows.
"""

import logging
from typing import Dict, List, Tuple

import pandas as pd

from evaluation.common import PreprocessLog
from evaluation.data import load_ktas, load_mimic
from evaluation.frozen import assert_frozen
from evaluation.llm_cache import CachedCompletion
from evaluation.llm_runner import LLMJob, make_index, run_job
from evaluation.splits import ktas_llm_sample, make_mimic_v2, make_or_load, subset

LLM_JOBS = [  # order = run order
    # --- MIMIC development set (prompt development; all calls already cached) ---
    LLMJob("mimic-dev:S4:kb=mimic-dev-train", "mimic", "S4", "mimic-dev-train", split="development"),
    LLMJob("mimic-dev:S4-promptv1:kb=mimic-dev-train", "mimic", "S4", "mimic-dev-train", split="dev-old-test",
           prompt="v1"),
    # --- MIMIC held-out test split (frozen configuration, run once) ---
    LLMJob("mimic:S4:kb=mimic-train", "mimic", "S4", "mimic-train"),
    LLMJob("mimic:S3:kb=none", "mimic", "S3", "none"),
    LLMJob("mimic:S4-promptv1:kb=mimic-train", "mimic", "S4", "mimic-train", prompt="v1"),
    # --- KTAS main evaluation (frozen configuration; full test split, 191 cases) ---
    LLMJob("ktas:S4:kb=mimic+ktas-train", "ktas", "S4", "mimic-all+ktas-train"),
    LLMJob("ktas:S3:kb=none", "ktas", "S3", "none"),
    # --- KTAS secondary: KB = MIMIC only (117-case sample; the 74-case extension runs last, if budget allows) ---
    LLMJob("ktas:S4:kb=mimic-all", "ktas", "S4", "mimic-all", split="test-sample"),
    LLMJob("ktas:S4:kb=mimic-all:extension", "ktas", "S4", "mimic-all", split="test-rest"),
]
EXTENSIONS = {"ktas:S4:kb=mimic-all:extension": "ktas:S4:kb=mimic-all"}   # extension job -> base job
DEV_SPLITS = ("development", "dev-old-test")


def quiet() -> None:
    for name in ("app", "agent_trace", "httpx", "evaluation"):
        logging.getLogger(name).setLevel(logging.WARNING)


def load_all() -> Dict:
    logs = {"mimic": PreprocessLog("MIMIC-IV-ED Demo v2.2"), "ktas": PreprocessLog("KTAS (Moon et al., 2019)")}
    data = {"mimic": load_mimic(logs["mimic"]), "ktas": load_ktas(logs["ktas"])}
    old_mimic = make_or_load(data["mimic"], "mimic")          # development-phase split (kept unchanged)
    v2 = make_mimic_v2(data["mimic"])
    splits = {"mimic": v2, "ktas": make_or_load(data["ktas"], "ktas")}
    parts = {
        # "validation" = the split used for tuning; for MIMIC protocol v2 that is the development set.
        "mimic": {"train": subset(data["mimic"], v2["train"]), "validation": subset(data["mimic"], v2["development"]),
                  "test": subset(data["mimic"], v2["test"])},
        "ktas": {k: subset(data["ktas"], ids) for k, ids in splits["ktas"].items()},
    }
    dev_parts = {"mimic": {k: subset(data["mimic"], ids) for k, ids in old_mimic.items()}}
    return {"data": data, "splits": splits, "parts": parts, "dev_parts": dev_parts, "old_mimic_split": old_mimic,
            "logs": logs}


def llm_cases(bundle: Dict, dataset: str, ktas_per_class: int, split: str = "test") -> pd.DataFrame:
    if split == "development":
        return bundle["parts"][dataset]["validation"]
    if split == "dev-old-test":
        return bundle["dev_parts"][dataset]["test"]
    if split in ("test-sample", "test-rest"):
        test = bundle["parts"][dataset]["test"]
        ids = set(ktas_llm_sample(test, per_class=ktas_per_class))
        keep = test["case_id"].isin(ids) if split == "test-sample" else ~test["case_id"].isin(ids)
        return test[keep].reset_index(drop=True)
    return bundle["parts"][dataset][split]


class KnowledgeBaseLeak(RuntimeError):
    """An evaluation knowledge base contains a validation/test record."""


def kb_frame(bundle: Dict, job: LLMJob):
    if job.kb == "mimic-dev-train":
        return bundle["dev_parts"]["mimic"]["train"]
    if job.kb == "mimic-all+ktas-train":
        kb = bundle["parts"]["ktas"]["train"]
        held = set(bundle["parts"]["ktas"]["validation"]["case_id"]) | set(bundle["parts"]["ktas"]["test"]["case_id"])
        if held & set(kb["case_id"]):
            raise KnowledgeBaseLeak("KTAS validation/test records in the evaluation knowledge base")
        return kb
    if job.kb.endswith("train"):
        return bundle["parts"][job.dataset]["train"]
    return None


def run_llm_jobs(bundle: Dict, completion: CachedCompletion, ktas_per_class: int = 40,
                 jobs: List[LLMJob] = None) -> Tuple[Dict[str, Dict], bool]:
    """Runs the LLM jobs in order; returns (results per job, all_complete)."""
    results, all_complete, exhausted = {}, True, False
    for job in jobs or LLM_JOBS:
        if job.split not in DEV_SPLITS:
            assert_frozen(job)   # held-out test and KTAS runs only with the frozen configuration
        cases = llm_cases(bundle, job.dataset, ktas_per_class, job.split)
        if exhausted:
            results[job.name] = {"job": job.__dict__, "records": [], "n_target": len(cases), "n_done": 0,
                                 "complete": False, "stopped_reason": "budget exhausted earlier in this run"}
            all_complete = False
            continue
        index = make_index(job.kb, kb_frame(bundle, job))
        print(f"[LLM] {job.name}: {len(cases)} cases", flush=True)
        res = run_job(job, cases, index, completion)
        results[job.name] = res
        print(f"[LLM] {job.name}: {res['n_done']}/{res['n_target']} done"
              + (f" -- stopped: {res['stopped_reason']}" if res["stopped_reason"] else ""), flush=True)
        if not res["complete"]:
            all_complete = False
            # A real budget stop ends the run; an offline cache miss does not (later jobs may be cached).
            exhausted = not getattr(completion, "offline", False)
    return results, all_complete
