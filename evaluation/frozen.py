"""
Frozen configuration for the held-out evaluations (MIMIC protocol-v2 test split and KTAS).

Frozen on 2026-11-21 after prompt development on the MIMIC development set. Everything that changes what
Agents 2-4 see or decide is hashed: prompt v2 template, weak-evidence rule, repair template, model and
decoding settings, retrieval weights / k, evidence threshold and agreement, repair attempts, NEWS2 switch.
`evaluation/frozen_config.json` stores the hash; any held-out LLM job refuses to run if it differs.

Knowledge-base change (2026-11-22, decided before any result of the affected KTAS jobs was seen): Agent 2 uses a
multi-source knowledge base (MIMIC-IV-ED + KTAS). The hashed configuration is unchanged; the record's
`knowledge_base` block and history document the change, and `assert_frozen` only allows the knowledge bases listed
in ALLOWED_KB for held-out jobs (KTAS validation/test records are never in an evaluation KB, see runner.kb_frame).
"""

import hashlib
import json
from typing import Dict

from app.core.config import get_settings
from app.services import llm_service
from evaluation.common import EVAL_DIR, read_json, write_json

FROZEN_PATH = EVAL_DIR / "frozen_config.json"


class ConfigNotFrozen(RuntimeError):
    """A held-out run was attempted with a configuration that differs from the frozen one."""


# Knowledge bases a held-out job may use (development jobs are not checked).
ALLOWED_KB = {"mimic": {"mimic-train", "none"}, "ktas": {"mimic-all+ktas-train", "mimic-all", "none"}}

KNOWLEDGE_BASE = {
    "decided_on": "2026-11-22",
    "decided_before_results": "decided before any result of the affected KTAS jobs was seen "
                              "(KTAS S4 KB=MIMIC+KTAS-train and S3 on 191 cases had not run)",
    "live_system": "all MIMIC-IV-ED Demo stays (222) + all KTAS records (1,267) = 1,489 cases, two sources",
    "evaluation_ktas_main": "all MIMIC-IV-ED Demo stays (222) + KTAS training split only (886) = 1,108 cases; "
                            "KTAS validation (190) and test (191) never in the knowledge base",
    "evaluation_ktas_secondary": "MIMIC-IV-ED only (222 stays; 117-case sample, extended to 191 if budget allows)",
    "evaluation_mimic_heldout": "MIMIC protocol-v2 training stays only (114); unchanged, not re-run",
    "source_labels": ["MIMIC-IV-ED", "KTAS"],
    "llm_evidence_text": "each retrieved case is prefixed with 'Source: <label>' when the knowledge base has more "
                         "than one source; single-source evidence text is byte-identical to before",
    "unchanged": "prompt v2, weak-evidence rule, repair template, model settings, retrieval weights, k=5, "
                 "LOW_EVIDENCE_THRESHOLD 0.50, agreement 0.6, repairs 2, NEWS2 on (config hash unchanged)",
}


def current_config() -> Dict:
    s = get_settings()
    return {
        "prompt_version": "v2",
        "prompt_v2_template_sha256": hashlib.sha256(llm_service.PROMPTS["v2"].encode("utf-8")).hexdigest(),
        "prompt_v1_template_sha256": hashlib.sha256(llm_service.PROMPTS["v1"].encode("utf-8")).hexdigest(),
        "weak_rule_sha256": hashlib.sha256(llm_service._WEAK_RULE.encode("utf-8")).hexdigest(),
        "repair_template_sha256": hashlib.sha256(llm_service._REPAIR_TEMPLATE.encode("utf-8")).hexdigest(),
        "model": s.GROQ_MODEL_NAME,
        "temperature": s.LLM_TEMPERATURE,
        "max_tokens": s.LLM_MAX_TOKENS,
        "reasoning_effort": s.LLM_REASONING_EFFORT,
        "max_repair_attempts": s.LLM_MAX_REPAIR_ATTEMPTS,
        "max_similar_cases": s.MAX_SIMILAR_CASES,
        "retrieval_weights": [s.RETRIEVAL_WEIGHT_COMPLAINT, s.RETRIEVAL_WEIGHT_DIAGNOSIS,
                              s.RETRIEVAL_WEIGHT_VITALS, s.RETRIEVAL_WEIGHT_MEDICATION],
        "low_evidence_threshold": s.LOW_EVIDENCE_THRESHOLD,
        "evidence_min_agreement": s.EVIDENCE_MIN_AGREEMENT,
        "news2_safety_net": s.NEWS2_SAFETY_NET_ENABLED,
    }


def config_hash(cfg: Dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()


def freeze(frozen_on: str = "2026-11-21", history: list = None, threshold_selection: Dict = None,
           knowledge_base: Dict = None) -> Dict:
    cfg = current_config()
    record = {"frozen_on": frozen_on, "reason": "prompt v2 developed on the MIMIC development set; "
              "held-out MIMIC test and KTAS are evaluated once with this configuration",
              "config": cfg, "sha256": config_hash(cfg), "history": history or []}
    if threshold_selection:
        record["low_evidence_threshold_selection"] = threshold_selection
    if knowledge_base:
        record["knowledge_base"] = knowledge_base
    write_json(FROZEN_PATH, record)
    return record


def frozen_record() -> Dict:
    return read_json(FROZEN_PATH)


def assert_frozen(job=None) -> None:
    """Raises ConfigNotFrozen unless the live configuration equals the frozen one and the job uses prompt v2/v1 as frozen."""
    if not FROZEN_PATH.exists():
        raise ConfigNotFrozen("evaluation/frozen_config.json missing")
    frozen = frozen_record()
    cfg = current_config()
    if config_hash(cfg) != frozen["sha256"]:
        diff = {k: (frozen["config"].get(k), v) for k, v in cfg.items() if frozen["config"].get(k) != v}
        raise ConfigNotFrozen(f"configuration differs from the frozen one: {diff}")
    if job is not None and job.prompt not in ("v1", "v2"):
        raise ConfigNotFrozen(f"unknown prompt {job.prompt}")
    if job is not None and job.dataset == "ktas" and job.prompt != "v2":
        raise ConfigNotFrozen("KTAS must use the frozen prompt v2")
    if job is not None and job.kb not in ALLOWED_KB.get(job.dataset, set()):
        raise ConfigNotFrozen(f"knowledge base {job.kb!r} not allowed for held-out {job.dataset} jobs")
    if job is not None and job.dataset == "ktas" and "knowledge_base" not in frozen:
        raise ConfigNotFrozen("knowledge-base change not recorded in evaluation/frozen_config.json")
