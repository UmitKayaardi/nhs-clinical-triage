"""
LLM systems for the offline evaluation, run through the SAME code as the
live API (app.services.triage_pipeline.run_clinical_agents):

  S3          LLM only: Agent 3 + Agent 4 schema guardrail, no historical evidence
              (empty knowledge base -> the prompt says no evidence was found)
  S4          Full system: Agents 2 + 3 + 4 incl. weak-evidence flag (WP2),
              repair loop and NEWS2 safety net (WP3)
  S4-noNEWS2  The same S4 runs, severity taken before the NEWS2 safety net
              (no extra LLM calls)

Knowledge bases: MIMIC evaluation uses MIMIC-train only (leakage control);
KTAS uses KB=MIMIC (all 222 stays, the deployed system) and KB=KTAS-train.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from app.services import retrieval_service as rs
from app.services.llm_service import LLMGenerationError
from app.services.trace import AgentTrace
from app.services.triage_pipeline import TriageInput, run_clinical_agents
from evaluation.baselines import build_kb, case_vitals, mimic_index, readonly_mimic_session
from evaluation.llm_cache import BudgetExhausted, CachedCompletion


@dataclass
class LLMJob:
    name: str            # e.g. "mimic:S4:kb=mimic-train"
    dataset: str         # mimic | ktas
    system: str          # S3 | S4
    kb: str              # none | mimic-train | mimic-all | ktas-train
    split: str = "test"  # test | validation
    prompt: str = "v2"   # Agent 3 prompt version (v1 = ablation of the previous release prompt)


def triage_input(row: pd.Series) -> TriageInput:
    def val(key):
        v = row.get(key)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    return TriageInput(
        complaint=row["complaint"],
        vitals=case_vitals(row),
        pain=val("pain"),
        consciousness=val("consciousness"),
        age=val("age"),
        gender=val("gender"),
        arrival_mode=val("arrival_mode"),
        injury=None if val("injury") is None else bool(row["injury"]),
    )


def make_index(kb: str, train_df: Optional[pd.DataFrame]):
    if kb == "none":
        return rs.build_index([])
    if kb == "mimic-all":
        return rs.build_index(rs.records_from_db(readonly_mimic_session()))
    if kb == "mimic-train":
        return mimic_index(train_df["stay_id"])
    if kb == "ktas-train":
        return build_kb("ktas", train_df)
    raise ValueError(kb)


def run_job(job: LLMJob, cases: pd.DataFrame, index, completion: CachedCompletion,
            progress_every: int = 10) -> Dict:
    """Runs one LLM system over `cases`. Stops early (complete=False) when the budget is exhausted."""
    records: List[Dict] = []
    stopped_reason = None
    for i, (_, row) in enumerate(cases.iterrows(), start=1):
        trace = AgentTrace()
        rec = {"system": job.system, "dataset": job.dataset, "kb": job.kb, "case_id": row["case_id"],
               "true": row["label"], "split": job.split, "prompt": job.prompt}
        attempts_before = completion.api_calls
        try:
            out = run_clinical_agents(None, triage_input(row), trace=trace,
                                      retrieve_kwargs={"index": index}, completion_fn=completion,
                                      prompt_version=job.prompt)
        except BudgetExhausted as exc:
            stopped_reason = str(exc)
            break
        except LLMGenerationError as exc:
            rec.update(pred=None, llm_severity=None, failed=True, error=str(exc)[:300], attempts=3,
                       first_pass_valid=False)
            records.append(rec)
            continue
        attempts = out.attempts
        rec.update(
            pred=out.triage_result.Severity.value,
            llm_severity=out.llm_severity,
            failed=False,
            confidence=out.triage_result.Confidence,
            news2_score=out.safety["news2_score"],
            safety_override=out.safety["safety_override"],
            evidence_strength=out.evidence["evidence_strength"],
            low_evidence=out.evidence["low_evidence"],
            top_similarity=out.evidence["top_similarity"],
            n_evidence=len(out.similar_cases),
            neighbour_labels=[c.severity for c in out.similar_cases],
            attempts=len(attempts),
            first_pass_valid=bool(attempts and attempts[0]["valid"]),
            repaired=len(attempts) > 1,
            tokens=sum(((a.get("usage") or {}).get("total_tokens") or 0) for a in attempts),
            latency_agent2_ms=out.timings_ms.get("agent2_retrieval"),
            latency_agent3_ms=out.timings_ms.get("agent3_llm"),
            latency_agent4_ms=round(out.timings_ms.get("agent3_4_reasoning_guardrail", 0)
                                    - out.timings_ms.get("agent3_llm", 0) + out.timings_ms.get("agent4_news2", 0), 2),
            api_calls=completion.api_calls - attempts_before,
        )
        records.append(rec)
        if progress_every and i % progress_every == 0:
            print(f"  {job.name}: {i}/{len(cases)} cases (api calls this run {completion.api_calls})", flush=True)
    return {"job": job.__dict__, "records": records, "n_target": len(cases), "n_done": len(records),
            "complete": len(records) == len(cases), "stopped_reason": stopped_reason}
