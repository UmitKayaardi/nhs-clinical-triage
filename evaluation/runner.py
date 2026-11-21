"""Orchestrates the evaluation stages used by scripts/evaluate.py."""

import logging
from typing import Dict, List, Tuple

import pandas as pd

from evaluation.common import PreprocessLog
from evaluation.data import load_ktas, load_mimic
from evaluation.llm_cache import CachedCompletion
from evaluation.llm_runner import LLMJob, make_index, run_job
from evaluation.splits import ktas_llm_sample, make_or_load, subset

LLM_JOBS = [  # order = run order (MIMIC first, then KTAS)
    LLMJob("mimic:S4:kb=mimic-train", "mimic", "S4", "mimic-train"),
    LLMJob("mimic:S3:kb=none", "mimic", "S3", "none"),
    LLMJob("ktas:S4:kb=mimic-all", "ktas", "S4", "mimic-all"),
    LLMJob("ktas:S4:kb=ktas-train", "ktas", "S4", "ktas-train"),
    LLMJob("ktas:S3:kb=none", "ktas", "S3", "none"),
]


def quiet() -> None:
    for name in ("app", "agent_trace", "httpx", "evaluation"):
        logging.getLogger(name).setLevel(logging.WARNING)


def load_all() -> Dict:
    logs = {"mimic": PreprocessLog("MIMIC-IV-ED Demo v2.2"), "ktas": PreprocessLog("KTAS (Moon et al., 2019)")}
    data = {"mimic": load_mimic(logs["mimic"]), "ktas": load_ktas(logs["ktas"])}
    splits = {name: make_or_load(df, name) for name, df in data.items()}
    parts = {name: {k: subset(data[name], ids) for k, ids in splits[name].items()} for name in data}
    return {"data": data, "splits": splits, "parts": parts, "logs": logs}


def llm_cases(bundle: Dict, dataset: str, ktas_per_class: int) -> pd.DataFrame:
    test = bundle["parts"][dataset]["test"]
    if dataset == "mimic":
        return test
    ids = set(ktas_llm_sample(test, per_class=ktas_per_class))
    return test[test["case_id"].isin(ids)].reset_index(drop=True)


def run_llm_jobs(bundle: Dict, completion: CachedCompletion, ktas_per_class: int = 40,
                 jobs: List[LLMJob] = None) -> Tuple[Dict[str, Dict], bool]:
    """Runs the LLM jobs in order; returns (results per job, all_complete)."""
    results, all_complete, exhausted = {}, True, False
    for job in jobs or LLM_JOBS:
        cases = llm_cases(bundle, job.dataset, ktas_per_class)
        if exhausted:
            results[job.name] = {"job": job.__dict__, "records": [], "n_target": len(cases), "n_done": 0,
                                 "complete": False, "stopped_reason": "budget exhausted earlier in this run"}
            all_complete = False
            continue
        index = make_index(job.kb, bundle["parts"][job.dataset]["train"] if job.kb.endswith("train") else None)
        print(f"[LLM] {job.name}: {len(cases)} cases", flush=True)
        res = run_job(job, cases, index, completion)
        results[job.name] = res
        print(f"[LLM] {job.name}: {res['n_done']}/{res['n_target']} done"
              + (f" -- stopped: {res['stopped_reason']}" if res["stopped_reason"] else ""), flush=True)
        if not res["complete"]:
            all_complete = False
            exhausted = True
    return results, all_complete
