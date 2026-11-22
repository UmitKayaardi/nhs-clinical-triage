"""
Builds every evaluation output: metrics.json, summary.md, errors_<dataset>.csv,
figures (300 dpi PNG), report_assets/figures and report_assets/preprocessing.md.
"""

import shutil
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

from app.core.config import get_settings
from evaluation import figures
from evaluation.baselines import (
    DEFAULT_WEIGHTS,
    build_kb,
    majority_predict,
    ml_fit_predict,
    prior_of,
    retrieve_all,
    s1_predict,
    tune_ml,
    tune_s1,
)
from evaluation.common import FIGURES_DIR, LABELS, ORDINAL, REPORT_ASSETS, RESULTS_DIR, SEED, write_json
from evaluation.evidence import tune_threshold
from evaluation.llm_runner import make_index
from evaluation.metrics import (
    bootstrap_ci,
    classification_metrics,
    mcnemar,
    summarise_cv,
)
from evaluation.frozen import config_hash, current_config, frozen_record
from evaluation.runner import DEV_SPLITS, LLM_JOBS, llm_cases

SYSTEM_NAMES = {
    "S0": "Majority class",
    "S1": "Retrieval-only (Agent 2 vote)",
    "S2a": "Logistic Regression",
    "S2b": "Random Forest",
    "S3": "LLM only (no evidence)",
    "S4": "Full system (Agents 2+3+4)",
    "S4-noNEWS2": "Full system without NEWS2 safety net",
    "S4-promptv1": "Full system with the previous release prompt (v1)",
    "H": "Triage nurse (KTAS_RN)",
}
AGE_BANDS = [(0, 39.999, "<40"), (40, 64.999, "40-64"), (65, 200, "65+")]


def _age_band(age) -> Optional[str]:
    if age is None or pd.isna(age):
        return None
    for lo, hi, name in AGE_BANDS:
        if lo <= age <= hi:
            return name
    return None


def _full_metrics(y_true, y_pred, proba=None, with_ci=True) -> Dict:
    m = classification_metrics(y_true, y_pred, proba)
    if with_ci and len(y_true) > 1:
        m["ci95"] = bootstrap_ci(y_true, y_pred)
    return m


# ------------------------------------------------------------------ LLM-free
def llm_free(dataset: str, parts: Dict[str, pd.DataFrame]) -> Dict:
    train, val, test = parts["train"], parts["validation"], parts["test"]
    out = {"tuning": {}, "test": {}, "predictions": {}}

    s1_tune = tune_s1(dataset, train, val)
    lr_tune = tune_ml("lr", dataset, train, val)
    rf_tune = tune_ml("rf", dataset, train, val)
    out["tuning"] = {
        "S1": {"best": s1_tune["best"], "grid_size": len(s1_tune["grid"]), "top5": s1_tune["grid"][:5]},
        "S2a": {"best": lr_tune["best"], "grid": lr_tune["grid"]},
        "S2b": {"best": rf_tune["best"], "grid": rf_tune["grid"]},
        "selection": ("macro-F1 on the development set" if dataset == "mimic" else "macro-F1 on the validation split")
                     + " (ties: accuracy, then smaller k)",
    }
    k, weights = s1_tune["best"]["k"], s1_tune["best"]["weights"]

    preds = {}
    s0, s0p = majority_predict(train["label"], len(test))
    preds["S0"] = (s0, s0p)
    index = build_kb(dataset, train)
    retrieved = retrieve_all(test, index, weights, 10)
    preds["S1"] = s1_predict(retrieved, k, prior_of(train["label"]))
    for name, tune, kind in (("S2a", lr_tune, "lr"), ("S2b", rf_tune, "rf")):
        p, pr, _ = ml_fit_predict(kind, dataset, tune["best"]["params"], train, test)
        preds[name] = (p, pr)
    if dataset == "ktas":
        preds["H"] = (test["nurse_label"].tolist(), None)

    y = test["label"].tolist()
    for name, (p, pr) in preds.items():
        out["test"][name] = _full_metrics(y, p, pr if name in ("S1", "S2a", "S2b") else None)
        out["predictions"][name] = dict(zip(test["case_id"], p))

    # Retrieval quality on the test split (production weights, k = 1/3/5) for the KB used by S4.
    out["retrieval_quality"] = retrieval_quality(dataset, parts)
    out["s1_config"] = {"k": k, "weights": weights}
    return out


def retrieval_quality(dataset: str, parts: Dict[str, pd.DataFrame]) -> Dict:
    test = parts["test"]
    kbs = {"mimic-train": parts["train"]} if dataset == "mimic" else {"ktas-train": parts["train"], "mimic-all": None}
    res = {}
    for kb, train_df in kbs.items():
        index = make_index(kb, train_df)
        retrieved = retrieve_all(test, index, DEFAULT_WEIGHTS, 5)
        row = {"kb": kb, "n_queries": len(test),
               "no_evidence_rate": float(np.mean([len(c) == 0 for c in retrieved])),
               "mean_top1_similarity": float(np.mean([c[0].similarity_score if c else 0.0 for c in retrieved]))}
        for kk in (1, 3, 5):
            vals = [np.mean([n.severity == t for n in c[:kk]]) for c, t in zip(retrieved, test["label"]) if c]
            row[f"precision_at_{kk}"] = float(np.mean(vals)) if vals else None
        res[kb] = row
    return res


def cross_validation(dataset: str, parts: Dict[str, pd.DataFrame], s1_cfg: Dict, tuning: Dict) -> Dict:
    dev = pd.concat([parts["train"], parts["validation"]], ignore_index=True)
    if dataset == "mimic":
        splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
        folds = list(splitter.split(dev, dev["label"], dev["group_id"]))
        method = "5-fold StratifiedGroupKFold on subject_id (train + development set, held-out test untouched)"
    else:
        splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
        folds = list(splitter.split(dev, dev["label"]))
        method = "5-fold StratifiedKFold (train+validation, test untouched)"
    scores = {s: [] for s in ("S0", "S1", "S2a", "S2b")}
    for tr_idx, te_idx in folds:
        tr, te = dev.iloc[tr_idx].reset_index(drop=True), dev.iloc[te_idx].reset_index(drop=True)
        y = te["label"].tolist()
        fold_preds = {"S0": majority_predict(tr["label"], len(te))[0]}
        ret = retrieve_all(te, build_kb(dataset, tr), s1_cfg["weights"], 10)
        fold_preds["S1"] = s1_predict(ret, s1_cfg["k"], prior_of(tr["label"]))[0]
        fold_preds["S2a"] = ml_fit_predict("lr", dataset, tuning["S2a"]["best"]["params"], tr, te)[0]
        fold_preds["S2b"] = ml_fit_predict("rf", dataset, tuning["S2b"]["best"]["params"], tr, te)[0]
        for name, p in fold_preds.items():
            m = classification_metrics(y, p)
            scores[name].append({"accuracy": m["accuracy"], "balanced_accuracy": m["balanced_accuracy"],
                                 "f1_macro": m["f1_macro"], "under_triage_rate": m["under_triage_rate"]})
    return {"method": method, "fold_sizes": [int(len(f[1])) for f in folds],
            "systems": {name: summarise_cv(v) for name, v in scores.items()}}


# ------------------------------------------------------------------ LLM systems
def llm_section(job_results: Dict[str, Dict], bundle: Dict, ktas_per_class: int) -> Dict:
    out = {}
    for job in LLM_JOBS:
        res = job_results.get(job.name)
        cases = llm_cases(bundle, job.dataset, ktas_per_class, job.split)
        if not res:
            out[job.name] = {"complete": False, "n_done": 0, "n_target": len(cases)}
            continue
        recs = [r for r in res["records"]]
        ok = [r for r in recs if not r.get("failed")]
        entry = {"job": res["job"], "complete": res["complete"], "n_done": res["n_done"], "n_target": res["n_target"],
                 "n_failed": len(recs) - len(ok), "stopped_reason": res.get("stopped_reason")}
        if ok:
            y = [r["true"] for r in ok]
            if job.system == "S3":
                entry["S3"] = _full_metrics(y, [r["llm_severity"] for r in ok])
            elif job.prompt == "v1":
                entry["S4-promptv1"] = _full_metrics(y, [r["pred"] for r in ok])
            else:
                entry["S4"] = _full_metrics(y, [r["pred"] for r in ok])
                entry["S4-noNEWS2"] = _full_metrics(y, [r["llm_severity"] for r in ok])
            entry["agent_performance"] = agent_performance(recs)
        out[job.name] = entry
    return out


def _lat(values: List[float]) -> Dict:
    v = np.array([x for x in values if x is not None], dtype=float)
    if not len(v):
        return {}
    return {"mean": float(v.mean()), "median": float(np.median(v)), "p95": float(np.percentile(v, 95)), "n": int(len(v))}


def agent_performance(recs: List[Dict]) -> Dict:
    ok = [r for r in recs if not r.get("failed")]
    n = len(recs)
    return {
        "n_cases": n,
        "guardrail_first_pass_valid_rate": float(np.mean([r.get("first_pass_valid", False) for r in recs])) if n else None,
        "repair_rate": float(np.mean([r.get("repaired", False) for r in ok])) if ok else None,
        "failed_after_repairs": int(sum(1 for r in recs if r.get("failed"))),
        "news2_override_count": int(sum(1 for r in ok if r.get("safety_override"))),
        "news2_available_rate": float(np.mean([r.get("news2_score") is not None for r in ok])) if ok else None,
        "low_evidence_flag_rate": float(np.mean([bool(r.get("low_evidence")) for r in ok])) if ok else None,
        "evidence_strength_counts": pd.Series([r.get("evidence_strength") for r in ok]).value_counts().to_dict() if ok else {},
        "confidence_counts": pd.Series([r.get("confidence") or "none" for r in ok]).value_counts().to_dict() if ok else {},
        "mean_tokens_per_case": float(np.mean([r.get("tokens", 0) for r in ok])) if ok else None,
        "latency_ms": {
            "agent2_retrieval": _lat([r.get("latency_agent2_ms") for r in ok]),
            "agent3_llm": _lat([r.get("latency_agent3_ms") for r in ok]),
            "agent4_guardrail_news2": _lat([r.get("latency_agent4_ms") for r in ok]),
        },
        "latency_note": "Agent 3 latency = original Groq API latency stored in the cache (cached re-runs reuse it)",
    }


# ------------------------------------------------------------------ analyses
def low_evidence_analysis(recs: List[Dict]) -> Dict:
    ok = [r for r in recs if not r.get("failed")]
    out = {}
    for flag in (True, False):
        part = [r for r in ok if bool(r.get("low_evidence")) == flag]
        key = "flagged_weak" if flag else "not_flagged"
        if part:
            t = [ORDINAL[r["true"]] for r in part]
            p = [ORDINAL[r["pred"]] for r in part]
            out[key] = {"n": len(part), "accuracy": float(np.mean(np.array(t) == np.array(p))),
                        "under_triage_rate": float(np.mean(np.array(p) < np.array(t)))}
        else:
            out[key] = {"n": 0}
    return out


def subgroup_table(df: pd.DataFrame, preds: Dict[str, Dict[str, str]], dataset: str) -> Dict:
    out = {}
    groupings = {"sex": df["gender"].fillna("unknown")}
    if dataset == "ktas":
        groupings["age_band"] = df["age"].map(_age_band).fillna("unknown")
    for system, p in preds.items():
        sys_out = {}
        for gname, groups in groupings.items():
            gres = {}
            for g in sorted(groups.unique()):
                mask = (groups == g).to_numpy()
                ids = df.loc[mask, "case_id"]
                y = df.loc[mask, "label"].tolist()
                yp = [p.get(i) for i in ids]
                keep = [i for i, v in enumerate(yp) if v is not None]
                if not keep:
                    continue
                y, yp = [y[i] for i in keep], [yp[i] for i in keep]
                m = classification_metrics(y, yp)
                gres[g] = {"n": len(y), "accuracy": m["accuracy"], "f1_macro": m["f1_macro"],
                           "under_triage_rate": m["under_triage_rate"]}
            sys_out[gname] = gres
        out[system] = sys_out
    return out


def errors_csv(dataset: str, cases: pd.DataFrame, recs: List[Dict], path) -> int:
    by_id = {r["case_id"]: r for r in recs if not r.get("failed")}
    rows = []
    for _, c in cases.iterrows():
        r = by_id.get(c["case_id"])
        if not r or r["pred"] == r["true"]:
            continue
        vit = ", ".join(f"{k}={c[k]:g}" for k in ("temperature", "heart_rate", "resp_rate", "o2sat", "sbp", "dbp")
                        if pd.notna(c[k]))
        rows.append({
            "case_id": c["case_id"], "complaint": c["complaint"], "vitals": vit,
            "pain": c["pain"], "gender": c["gender"], "age": c.get("age"),
            "consciousness": c.get("consciousness"),
            "true": r["true"], "predicted": r["pred"], "llm_severity_before_news2": r["llm_severity"],
            "error_type": "under-triage" if ORDINAL[r["pred"]] < ORDINAL[r["true"]] else "over-triage",
            "top1_similarity": r.get("top_similarity"), "evidence_strength": r.get("evidence_strength"),
            "low_evidence_flag": r.get("low_evidence"), "news2_score": r.get("news2_score"),
            "news2_override": r.get("safety_override"), "kb": r.get("kb"),
            **({"nurse_label": c["nurse_label"]} if dataset == "ktas" else {}),
        })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    return len(rows)


# ------------------------------------------------------------------ main builder
def build_everything(bundle: Dict, job_results: Dict, llm_stats: Dict, llm_complete: bool, args) -> Dict:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    ktas_pc = getattr(args, "ktas_llm_sample", 40)
    metrics: Dict = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "seed": SEED,
        "labels": LABELS,
        "label_mapping": {"mimic": "ESI 1-2 High, 3 Medium, 4-5 Low", "ktas": "KTAS 1-2 High, 3 Medium, 4-5 Low"},
        "systems": SYSTEM_NAMES,
        "llm": {"model": settings.GROQ_MODEL_NAME, "temperature": settings.LLM_TEMPERATURE,
                "max_tokens": settings.LLM_MAX_TOKENS, "reasoning_effort": settings.LLM_REASONING_EFFORT,
                "max_repair_attempts": settings.LLM_MAX_REPAIR_ATTEMPTS, "run_stats": llm_stats,
                "all_llm_runs_complete": llm_complete},
        "datasets": {},
        "protocol": {
            "mimic": ("protocol v2: development set = old validation + old test splits (62 stays, 26 patients; prompt "
                      "v1 -> v2 developed here, LLM-free tuning uses it); held-out test = 31 stays from 9 patients drawn "
                      "from the old training patients only (never an LLM query before), evaluated once with the frozen "
                      "configuration; knowledge base and ML training data for the test run = remaining 114 stays / 21 "
                      "patients"),
            "ktas": "external evaluation with the frozen configuration (prompt v2), never used for development",
            "frozen_config": frozen_record(),
            "live_config_matches_frozen": config_hash(current_config()) == frozen_record()["sha256"],
        },
    }

    # Preprocessing log -> metrics + report_assets/preprocessing.md
    metrics["preprocessing"] = {k: v.as_dict() for k, v in bundle["logs"].items()}

    for dataset in ("mimic", "ktas"):
        print(f"[report] {dataset}: LLM-free systems, tuning, CV ...", flush=True)
        parts = bundle["parts"][dataset]
        from evaluation.splits import describe
        free = llm_free(dataset, parts)
        cv = cross_validation(dataset, parts, free["s1_config"], free["tuning"])
        ds = {"split_summary": describe(bundle["data"][dataset], bundle["splits"][dataset]),
              "tuning": free["tuning"], "s1_config": free["s1_config"], "test": free["test"],
              "cross_validation": cv, "retrieval_quality": free["retrieval_quality"]}
        if dataset == "mimic":
            # Frozen value: reproduced with the development-phase split it was chosen on.
            # Re-selected on 2026-11-22 with the same rule on NON-TEST data only: out-of-fold over the protocol-v2
            # train (114) + development (62) stays; no held-out test stay involved. Result 0.50 = unchanged.
            ds["low_evidence_threshold"] = tune_threshold(parts["train"], parts["validation"])
            ds["low_evidence_threshold"]["chosen_on"] = ("non-test data only: 5-fold patient-grouped OOF over protocol-v2 "
                                                          "train (114) + development (62) stays; held-out test not used")
            ds["low_evidence_threshold"]["previous_selection"] = ("development phase (21 Nov): same rule over old "
                                                                   "train + old validation, result 0.50")
            ds["low_evidence_threshold"]["config_value"] = settings.LOW_EVIDENCE_THRESHOLD
        metrics["datasets"][dataset] = ds
        free_preds = free["predictions"]

        # LLM systems + like-for-like subset
        jobs = [j for j in LLM_JOBS if j.dataset == dataset]
        llm = llm_section({j.name: job_results.get(j.name) for j in jobs if job_results.get(j.name)}, bundle, ktas_pc)
        ds["llm_systems"] = {j.name: llm[j.name] for j in jobs if j.split == "test" and j.name in llm}
        ds["llm_development"] = {j.name: llm[j.name] for j in jobs if j.split in DEV_SPLITS and j.name in llm}
        cases = llm_cases(bundle, dataset, ktas_pc)
        y_sub = cases["label"].tolist()
        if dataset == "ktas":
            sub = {name: _full_metrics(y_sub, [free_preds[name][i] for i in cases["case_id"]])
                   for name in ("S0", "S1", "S2a", "S2b", "H")}
            ds["llm_subset"] = {"n": len(cases), "class_counts": cases["label"].value_counts().to_dict(),
                                "note": f"stratified sample of the KTAS test split, up to {ktas_pc} per class "
                                        f"(High has only {int((parts['test']['label'] == 'High').sum())} test cases)",
                                "systems": sub}

        # Comparisons, subgroup, low-evidence, errors
        s4_jobs = [j for j in jobs if j.system == "S4" and j.split == "test" and j.prompt == "v2"]
        best_free = max(("S1", "S2a", "S2b"), key=lambda s: free["tuning"][s]["best"]["f1_macro"])
        ds["best_non_llm_by_validation"] = best_free
        comparisons, low_ev, subgroups = {}, {}, {}
        sub_df = cases
        subgroup_preds = {"S2b": free_preds["S2b"]}
        if dataset == "ktas":
            subgroup_preds["H"] = free_preds["H"]
        for job in s4_jobs:
            res = job_results.get(job.name)
            if not res or not res["records"]:
                continue
            recs = [r for r in res["records"] if not r.get("failed")]
            ids = [r["case_id"] for r in recs]
            y = [r["true"] for r in recs]
            s4 = [r["pred"] for r in recs]
            comparisons[f"{job.name} vs {best_free}"] = mcnemar(y, s4, [free_preds[best_free][i] for i in ids])
            comparisons[f"{job.name} vs S4-noNEWS2"] = mcnemar(y, s4, [r["llm_severity"] for r in recs])
            if dataset == "ktas":
                comparisons[f"{job.name} vs H"] = mcnemar(y, s4, [free_preds["H"][i] for i in ids])
            for other in [j for j in jobs if j.split == "test" and j.name != job.name and j.kb in (job.kb, "none")
                          and (j.system == "S3" or j.prompt == "v1")]:
                ores = job_results.get(other.name)
                if not ores or not ores["records"]:
                    continue
                omap = {r["case_id"]: r for r in ores["records"] if not r.get("failed")}
                common = [r for r in recs if r["case_id"] in omap]
                if common:
                    key = "llm_severity" if other.system == "S3" else "pred"
                    comparisons[f"{job.name} vs {other.name}"] = mcnemar(
                        [r["true"] for r in common], [r["pred"] for r in common],
                        [omap[r["case_id"]][key] for r in common])
            low_ev[job.name] = low_evidence_analysis(recs)
            subgroup_preds[f"S4 ({job.kb})"] = {r["case_id"]: r["pred"] for r in recs}
            if job.kb in ("mimic-train", "mimic-all"):
                n_err = errors_csv(dataset, cases, recs, RESULTS_DIR / f"errors_{dataset}.csv")
                ds["errors_file"] = {"path": f"evaluation/results/errors_{dataset}.csv", "rows": n_err, "system": job.name}
            if job.kb == "ktas-train":
                errors_csv(dataset, cases, recs, RESULTS_DIR / f"errors_{dataset}_kb-ktas.csv")
        ds["mcnemar"] = comparisons
        ds["low_evidence_analysis"] = low_ev
        ds["subgroups"] = subgroup_table(sub_df, subgroup_preds, dataset)
        ds["subgroups_full_test_llm_free"] = subgroup_table(parts["test"], {"S2b": free_preds["S2b"],
                                                           **({"H": free_preds["H"]} if dataset == "ktas" else {})},
                                                           dataset)

    print("[report] figures ...", flush=True)
    metrics["figures"] = figures.make_all(metrics, job_results)
    write_json(RESULTS_DIR / "metrics.json", metrics)
    (RESULTS_DIR / "summary.md").write_text(summary_markdown(metrics), encoding="utf-8")
    write_preprocessing_md(metrics)
    dest = REPORT_ASSETS / "figures"
    dest.mkdir(parents=True, exist_ok=True)
    for png in FIGURES_DIR.glob("*.png"):
        shutil.copy2(png, dest / png.name)
    print(f"[report] wrote {RESULTS_DIR / 'metrics.json'}, summary.md, {len(list(FIGURES_DIR.glob('*.png')))} figures",
          flush=True)
    return metrics


# ------------------------------------------------------------------ markdown
def _f(x, pct=False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.3f}"


def _ci(m, key, pct=True) -> str:
    ci = (m.get("ci95") or {}).get(key)
    return f"[{_f(ci['low'], pct)}, {_f(ci['high'], pct)}]" if ci else ""


def _row(name: str, m: Dict) -> str:
    return (f"| {name} | {m['n']} | {_f(m['accuracy'], True)} {_ci(m, 'accuracy')} | {_f(m['balanced_accuracy'], True)} | "
            f"{_f(m['f1_macro'])} {_ci(m, 'f1_macro', pct=False)} | {_f(m['f1_weighted'])} | {_f(m['kappa_linear'])} | "
            f"{_f(m['high_recall'], True)} | {_f(m['under_triage_rate'], True)} {_ci(m, 'under_triage_rate')} | "
            f"{_f(m['over_triage_rate'], True)} | {_f(m.get('roc_auc_macro_ovr'))} |")


HEADER = ("| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | "
          "High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |\n|---|---|---|---|---|---|---|---|---|---|---|")


def summary_markdown(metrics: Dict) -> str:
    lines = ["# Evaluation summary (tables only)", "",
             f"Protocol: MIMIC {metrics['protocol']['mimic']}. KTAS: {metrics['protocol']['ktas']}. "
             f"Frozen configuration sha256 {metrics['protocol']['frozen_config']['sha256'][:16]}... "
             f"(live config matches: {metrics['protocol']['live_config_matches_frozen']}).", "",
             f"Generated {metrics['generated_at']} by `python scripts/evaluate.py --all`; seed {metrics['seed']}. "
             f"LLM: {metrics['llm']['model']}, temperature {metrics['llm']['temperature']}, reasoning_effort "
             f"{metrics['llm']['reasoning_effort']}. All LLM runs complete: {metrics['llm']['all_llm_runs_complete']}.", ""]
    for dataset, ds in metrics["datasets"].items():
        lines += [f"## {dataset.upper()}", "", "### Split", "", "| Split | Cases | Groups | Low | Medium | High |",
                  "|---|---|---|---|---|---|"]
        for name, s in ds["split_summary"].items():
            c = s["class_counts"]
            lines.append(f"| {name} | {s['n_cases']} | {s['n_groups']} | {c['Low']} | {c['Medium']} | {c['High']} |")
        lines += ["", "### {} -- LLM-free systems".format("Held-out test split" if dataset == "mimic" else "Test split"),
                  "", HEADER]
        for name, m in ds["test"].items():
            lines.append(_row(f"{name} {SYSTEM_NAMES[name]}", m))
        lines += ["", "### LLM systems ({})".format("KTAS test sample, external evaluation, frozen configuration"
                                                    if dataset == "ktas" else
                                                    "MIMIC held-out test split, frozen configuration, run once"),
                  "", HEADER]
        for job, entry in ds["llm_systems"].items():
            for sysname in ("S3", "S4", "S4-noNEWS2", "S4-promptv1"):
                if sysname in entry:
                    tag = "" if entry["complete"] else f" (INCOMPLETE {entry['n_done']}/{entry['n_target']})"
                    lines.append(_row(f"{sysname} [{job.split(':')[-1]}]{tag}", entry[sysname]))
        if ds.get("llm_development"):
            lines += ["", "### Development set results (prompt development v1 -> v2; NOT held-out)", "",
                      "Development set = old validation + old test splits; knowledge base = old training split.", "",
                      HEADER]
            for job, entry in ds["llm_development"].items():
                for sysname in ("S4", "S4-noNEWS2", "S4-promptv1"):
                    if sysname in entry:
                        lines.append(_row(f"{sysname} development [{job.split(':')[-1]}]", entry[sysname]))
        if dataset == "ktas" and "llm_subset" in ds:
            lines += ["", f"### Same {ds['llm_subset']['n']}-case KTAS subset -- LLM-free systems and nurse", "", HEADER]
            for name, m in ds["llm_subset"]["systems"].items():
                lines.append(_row(f"{name} {SYSTEM_NAMES[name]}", m))
        tune_name = "development set" if dataset == "mimic" else "validation split"
        lines += ["", "### 5-fold cross-validation (train + {}; held-out test untouched)".format(tune_name), "",
                  f"Method: {ds['cross_validation']['method']}", "",
                  "| System | Accuracy mean ± sd | Macro-F1 mean ± sd | Balanced acc. mean ± sd | Under-triage mean ± sd |",
                  "|---|---|---|---|---|"]
        for name, cvm in ds["cross_validation"]["systems"].items():
            lines.append(f"| {name} | {_f(cvm['accuracy']['mean'])} ± {_f(cvm['accuracy']['std'])} | "
                         f"{_f(cvm['f1_macro']['mean'])} ± {_f(cvm['f1_macro']['std'])} | "
                         f"{_f(cvm['balanced_accuracy']['mean'])} ± {_f(cvm['balanced_accuracy']['std'])} | "
                         f"{_f(cvm['under_triage_rate']['mean'])} ± {_f(cvm['under_triage_rate']['std'])} |")
        lines += ["", f"### Tuned hyperparameters (macro-F1 on the {tune_name})", "",
                  f"- S1: k={ds['s1_config']['k']}, weights={ds['s1_config']['weights']} "
                  f"(val macro-F1 {_f(ds['tuning']['S1']['best']['f1_macro'])})",
                  f"- S2a: {ds['tuning']['S2a']['best']['params']} (val macro-F1 {_f(ds['tuning']['S2a']['best']['f1_macro'])})",
                  f"- S2b: {ds['tuning']['S2b']['best']['params']} (val macro-F1 {_f(ds['tuning']['S2b']['best']['f1_macro'])})",
                  f"- Best non-LLM system by {tune_name} macro-F1: {ds['best_non_llm_by_validation']}"]
        lines += ["", "### Retrieval quality (production weights, test queries)", "",
                  "| KB | Queries | No-evidence rate | Mean top-1 similarity | P@1 | P@3 | P@5 |", "|---|---|---|---|---|---|---|"]
        for kb, r in ds["retrieval_quality"].items():
            lines.append(f"| {kb} | {r['n_queries']} | {_f(r['no_evidence_rate'], True)} | {_f(r['mean_top1_similarity'])} | "
                         f"{_f(r['precision_at_1'])} | {_f(r['precision_at_3'])} | {_f(r['precision_at_5'])} |")
        if ds.get("mcnemar"):
            lines += ["", "### McNemar tests (exact)", "", "| Comparison | A right / B wrong | A wrong / B right | p |",
                      "|---|---|---|---|"]
            for k, v in ds["mcnemar"].items():
                lines.append(f"| {k} | {v['a_correct_b_wrong']} | {v['a_wrong_b_correct']} | {v['p_value_exact']:.4f} |")
        perf = ([(f"DEVELOPMENT {k}", v["agent_performance"]) for k, v in ds.get("llm_development", {}).items()
                 if "agent_performance" in v]
                + [(k, v["agent_performance"]) for k, v in ds["llm_systems"].items() if "agent_performance" in v])
        if perf:
            lines += ["", "### Agent performance", "",
                      "| Job | Cases | First-pass valid | Repair rate | Failed | NEWS2 overrides | Weak-evidence flags | "
                      "Agent 2 ms (median) | Agent 3 ms (median / p95) | Agent 4 ms (median) | Tokens/case |",
                      "|---|---|---|---|---|---|---|---|---|---|---|"]
            for k, a in perf:
                lat = a["latency_ms"]
                lines.append(f"| {k} | {a['n_cases']} | {_f(a['guardrail_first_pass_valid_rate'], True)} | "
                             f"{_f(a['repair_rate'], True)} | {a['failed_after_repairs']} | {a['news2_override_count']} | "
                             f"{_f(a['low_evidence_flag_rate'], True)} | {lat['agent2_retrieval'].get('median', 0):.1f} | "
                             f"{lat['agent3_llm'].get('median', 0):.0f} / {lat['agent3_llm'].get('p95', 0):.0f} | "
                             f"{lat['agent4_guardrail_news2'].get('median', 0):.2f} | {a['mean_tokens_per_case'] or 0:.0f} |")
        if ds.get("low_evidence_analysis"):
            lines += ["", "### Weak-evidence flag (S4)", "", "| Job | Flagged n | Flagged acc. | Flagged under-triage | "
                      "Not flagged n | Not flagged acc. | Not flagged under-triage |", "|---|---|---|---|---|---|---|"]
            for k, v in ds["low_evidence_analysis"].items():
                a, b = v["flagged_weak"], v["not_flagged"]
                lines.append(f"| {k} | {a['n']} | {_f(a.get('accuracy'), True)} | {_f(a.get('under_triage_rate'), True)} | "
                             f"{b['n']} | {_f(b.get('accuracy'), True)} | {_f(b.get('under_triage_rate'), True)} |")
        if ds.get("subgroups"):
            lines += ["", "### Subgroups (LLM case set)", "", "| System | Grouping | Group | n | Accuracy | Macro-F1 | Under-triage |",
                      "|---|---|---|---|---|---|---|"]
            for system, groups in ds["subgroups"].items():
                for gname, gres in groups.items():
                    for g, v in gres.items():
                        lines.append(f"| {system} | {gname} | {g} | {v['n']} | {_f(v['accuracy'], True)} | "
                                     f"{_f(v['f1_macro'])} | {_f(v['under_triage_rate'], True)} |")
        if dataset == "mimic":
            t = ds["low_evidence_threshold"]
            lines += ["", "### LOW_EVIDENCE_THRESHOLD selection", "", f"- Rule: {t['rule']}", f"- Signal: {t['signal']}",
                      f"- Chosen (development OOF, n={t['n_development']}): {t['chosen_threshold']} -> {t['chosen_row']}",
                      f"- Validation-only choice (n={t['n_validation']}): {t['validation_only_choice']}",
                      f"- Value in config: {t['config_value']}"]
        warn = [f"{n}: {m['warning']}" for n, m in ds["test"].items() if "warning" in m]
        if warn:
            lines += ["", "### Warnings", ""] + [f"- {w}" for w in warn[:3]]
        lines.append("")
    lines += ["## Figures", ""] + [f"- `{f}`" for f in metrics.get("figures", [])]
    return "\n".join(lines) + "\n"


def write_preprocessing_md(metrics: Dict) -> None:
    lines = ["# Preprocessing and encoding log (generated by scripts/evaluate.py)", ""]
    for key, log in metrics["preprocessing"].items():
        lines += [f"## {log['dataset']}", "", "| # | Step | Rows before | Rows after | Detail |", "|---|---|---|---|---|"]
        for i, s in enumerate(log["steps"], 1):
            lines.append(f"| {i} | {s['step']} | {s['rows_before']} | {s['rows_after']} | {s['detail']} |")
        lines.append("")
    lines += ["## Encoding for the ML baselines (S2a/S2b)", "",
              "| Feature group | Columns | Transformation |", "|---|---|---|",
              "| Text | chief complaint | shared clinical normaliser (`retrieval_service._normalise`: abbreviations, lay synonyms, "
              "stop-words, plural stripping) -> TF-IDF (sklearn TfidfVectorizer) |",
              "| Numeric | temperature (F), heart_rate, resp_rate, o2sat, sbp, dbp, pain (+ age for KTAS) | median imputation + "
              "missing-indicator columns -> StandardScaler |",
              "| Categorical | gender (+ consciousness, arrival_mode, injury for KTAS) | OneHotEncoder(handle_unknown='ignore') |",
              "| Label | ESI / KTAS_expert | 1-2 High, 3 Medium, 4-5 Low |", "",
              "## Encoding for the retrieval agent (S1/S4) and the LLM (S3/S4)", "",
              "| Input | Encoding |", "|---|---|",
              "| Chief complaint | normalised tokens -> TF-IDF cosine vs complaint, diagnosis and medication fields of each KB case |",
              "| Vitals | Gaussian kernel on clinically scaled differences (scales: temp 2 F, HR 25, RR 6, SpO2 4, SBP 25, DBP 15) |",
              "| LLM user message | 'Patient statement' + 'Structured intake data' lines (age, sex, vitals, pain, AVPU, arrival, injury) |",
              "| NEWS2 | RR, SpO2 (scale 1), SBP, HR, temperature (F->C), consciousness when known; room air assumed |", ""]
    path = REPORT_ASSETS / "preprocessing.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
