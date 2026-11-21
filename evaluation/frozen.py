"""
Frozen configuration for the held-out evaluations (MIMIC protocol-v2 test split and KTAS).

Frozen on 2026-11-21 after prompt development on the MIMIC development set. Everything that changes what
Agents 2-4 see or decide is hashed: prompt v2 template, weak-evidence rule, repair template, model and
decoding settings, retrieval weights / k, evidence threshold and agreement, repair attempts, NEWS2 switch.
`evaluation/frozen_config.json` stores the hash; any held-out LLM job refuses to run if it differs.
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


def freeze() -> Dict:
    cfg = current_config()
    record = {"frozen_on": "2026-11-21", "reason": "prompt v2 developed on the MIMIC development set; "
              "held-out MIMIC test and KTAS are evaluated once with this configuration",
              "config": cfg, "sha256": config_hash(cfg)}
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
