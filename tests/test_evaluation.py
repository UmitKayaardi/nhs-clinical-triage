"""WP1 -- offline evaluation helpers: labels, splits, leakage control, metrics, KTAS cleaning, LLM cache."""

import json

import numpy as np
import pandas as pd
import pytest

from app.models.mimic_models import SeverityLevel, map_acuity_to_severity
from app.services import retrieval_service
from evaluation import llm_cache
from evaluation.common import SPLITS_DIR, ktas_to_severity
from evaluation.data import _ktas_numeric, _translate_complaint, load_ktas, load_mimic
from evaluation.metrics import bootstrap_ci, classification_metrics, mcnemar, under_over_triage
from evaluation.splits import ktas_llm_sample, subset


def test_label_mappings():
    assert [map_acuity_to_severity(a) for a in (1.0, 2.0, 3.0, 4.0, 5.0)] == [
        SeverityLevel.HIGH, SeverityLevel.HIGH, SeverityLevel.MEDIUM, SeverityLevel.LOW, SeverityLevel.LOW]
    assert [ktas_to_severity(k) for k in (1, 2, 3, 4, 5)] == ["High", "High", "Medium", "Low", "Low"]
    with pytest.raises(ValueError):
        ktas_to_severity(6)


def test_saved_mimic_split_has_no_patient_overlap_and_is_complete():
    data = load_mimic()
    saved = json.loads((SPLITS_DIR / "mimic_split.json").read_text(encoding="utf-8"))
    splits = saved["splits"]
    groups = {k: set(subset(data, ids)["group_id"]) for k, ids in splits.items()}
    assert not (groups["train"] & groups["validation"])
    assert not (groups["train"] & groups["test"])
    assert not (groups["validation"] & groups["test"])
    assert sum(len(v) for v in splits.values()) == len(data) == 207
    assert saved["seed"] == 42


def test_saved_ktas_split_is_stratified_and_sample_is_balanced():
    data = load_ktas()
    splits = json.loads((SPLITS_DIR / "ktas_split.json").read_text(encoding="utf-8"))["splits"]
    assert sum(len(v) for v in splits.values()) == len(data) == 1267
    test = subset(data, splits["test"])
    sample = test[test["case_id"].isin(ktas_llm_sample(test, per_class=40))]
    counts = sample["label"].value_counts().to_dict()
    assert counts["Low"] == 40 and counts["Medium"] == 40 and counts["High"] == min(40, (test["label"] == "High").sum())


def test_allowed_stay_ids_prevents_leakage(db):
    # Stay 1 is the exact "Chest pain" match; restricted to other stays it can never be returned.
    full = retrieval_service.find_similar_cases(db, "chest pain")
    assert full[0].stay_id == 1
    restricted = retrieval_service.find_similar_cases(db, "chest pain", allowed_stay_ids=[2, 3, 4, 5, 6, 7, 8])
    assert restricted and all(c.stay_id != 1 for c in restricted)
    # Production behaviour (no argument) is unchanged.
    assert retrieval_service.find_similar_cases(db, "chest pain") == full


def test_evaluation_index_never_returns_a_test_stay_as_its_own_evidence():
    from evaluation.baselines import case_vitals, mimic_index

    data = load_mimic()
    splits = json.loads((SPLITS_DIR / "mimic_split.json").read_text(encoding="utf-8"))["splits"]
    train, test = subset(data, splits["train"]), subset(data, splits["test"])
    index = mimic_index(train["stay_id"])
    test_ids = set(test["stay_id"])
    for _, row in test.iterrows():
        cases = retrieval_service.find_similar_cases(None, row["complaint"], case_vitals(row), limit=10, index=index)
        assert not ({c.stay_id for c in cases} & test_ids)


def test_metrics_on_a_hand_made_example():
    y_true = ["High", "High", "Medium", "Low", "Low"]
    y_pred = ["High", "Medium", "Medium", "Medium", "Low"]
    m = classification_metrics(y_true, y_pred)
    assert m["accuracy"] == pytest.approx(0.6)
    assert m["under_triage_rate"] == pytest.approx(0.2) and m["over_triage_rate"] == pytest.approx(0.2)
    assert m["high_recall"] == pytest.approx(0.5)
    assert m["per_class"]["Medium"]["precision"] == pytest.approx(1 / 3)
    assert m["confusion_matrix"] == [[1, 1, 0], [0, 1, 0], [0, 1, 1]]   # rows Low, Medium, High
    assert m["balanced_accuracy"] == pytest.approx((0.5 + 1 + 0.5) / 3)
    assert under_over_triage(["High"], ["Low"])["under_triage_n"] == 1
    ci = bootstrap_ci(y_true, y_pred, n_boot=200)
    assert ci["accuracy"]["low"] <= 0.6 <= ci["accuracy"]["high"]


def test_mcnemar_counts_discordant_pairs():
    t = ["High"] * 10
    a = ["High"] * 8 + ["Low"] * 2
    b = ["Low"] * 6 + ["High"] * 4
    r = mcnemar(t, a, b)
    assert (r["a_correct_b_wrong"], r["a_wrong_b_correct"]) == (6, 2)
    assert 0 < r["p_value_exact"] < 1


def test_ktas_cleaning_rules():
    assert _translate_complaint("흉통") == ("chest pain", "translated")
    assert _translate_complaint("F/C, C/S")[0] == "fever chills, cough sputum"
    assert _translate_complaint("Pain, Αnus")[0] == "Pain, Anus"          # Greek alpha folded
    assert _translate_complaint("??")[1] == "unreadable"
    values, unmeasurable, commas = _ktas_numeric(pd.Series(["36,5", "측불", "120", "#BOÞ!", None]))
    assert values.iloc[0] == 36.5 and np.isnan(values.iloc[1]) and np.isnan(values.iloc[3])
    assert unmeasurable == 1 and commas == 1


def test_ktas_loader_converts_units_and_codes():
    df = load_ktas()
    assert len(df) == 1267
    first = df.iloc[0]
    assert first["temperature"] == pytest.approx(36.6 * 9 / 5 + 32, abs=0.1)   # 36.6 C -> F
    assert first["gender"] == "M" and first["consciousness"] == "alert" and first["arrival_mode"] == "private car"
    for leak in ("KTAS_RN", "KTAS_expert", "mistriage", "Error_group", "Length of stay_min"):
        assert leak not in df.columns


def test_llm_cache_hit_and_miss(tmp_path, monkeypatch):
    calls = []

    def fake(messages, params):
        calls.append(1)
        return '{"Severity": "Low"}', {"latency_ms": 1.0, "usage": {"total_tokens": 10}}

    monkeypatch.setattr(llm_cache.llm_service, "groq_completion", fake)
    path = tmp_path / "cache.jsonl"
    msgs, params = [{"role": "user", "content": "hi"}], {"model": "m", "temperature": 0}
    c1 = llm_cache.CachedCompletion(max_calls=5, path=path)
    assert c1(msgs, params)[1]["cached"] is False
    assert c1(msgs, params)[1]["cached"] is True
    assert len(calls) == 1
    # A new process reads the file: still a hit; offline mode never calls the API.
    c2 = llm_cache.CachedCompletion(max_calls=0, path=path, offline=True)
    assert c2(msgs, params)[0] == '{"Severity": "Low"}'
    with pytest.raises(llm_cache.BudgetExhausted):
        c2([{"role": "user", "content": "other"}], params)
    with pytest.raises(llm_cache.BudgetExhausted):
        llm_cache.CachedCompletion(max_calls=0, path=path)([{"role": "user", "content": "new"}], params)


def test_mimic_v2_heldout_split_is_clean():
    from evaluation.splits import V2_PATH

    data = load_mimic()
    old = json.loads((SPLITS_DIR / "mimic_split.json").read_text(encoding="utf-8"))["splits"]
    v2 = json.loads(V2_PATH.read_text(encoding="utf-8"))["splits"]
    groups = {k: set(subset(data, ids)["group_id"]) for k, ids in v2.items()}
    assert not (groups["test"] & groups["development"]) and not (groups["test"] & groups["train"])
    assert not (groups["train"] & groups["development"])
    # Development = the development-phase validation + test splits; held-out test only from old-train patients.
    assert sorted(v2["development"]) == sorted(old["validation"] + old["test"])
    assert set(v2["test"]) <= set(old["train"]) and set(v2["train"]) <= set(old["train"])
    assert sum(len(v) for v in v2.values()) == 207 and 28 <= len(v2["test"]) <= 34


def test_frozen_configuration_guard(monkeypatch):
    from app.core.config import get_settings
    from evaluation.frozen import ConfigNotFrozen, assert_frozen
    from evaluation.runner import LLM_JOBS

    for job in LLM_JOBS:
        if job.dataset == "ktas":
            assert job.prompt == "v2"
    assert_frozen()  # the live configuration equals evaluation/frozen_config.json
    monkeypatch.setattr(get_settings(), "LOW_EVIDENCE_THRESHOLD", 0.42)
    with pytest.raises(ConfigNotFrozen):
        assert_frozen()
