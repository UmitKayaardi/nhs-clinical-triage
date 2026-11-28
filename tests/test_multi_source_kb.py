"""Agent 2 multi-source knowledge base (MIMIC-IV-ED + KTAS), decided 2026-11-22."""

import pandas as pd
import pytest

from app.services import retrieval_service as rs


def _mimic_record(stay_id, complaint, severity="High"):
    return rs._StayRecord(stay_id=stay_id, chief_complaint=complaint, complaint_tokens=rs._normalise(complaint),
                          severity=severity, diagnoses=["Chest pain, unspecified"], vitals={}, treatments=[],
                          disposition="ADMITTED")


def _ktas_record(record_id, complaint, severity="Medium"):
    return rs.ktas_record(record_id, complaint, severity, "Angina", {"heart_rate": 90.0}, "Admission")


def test_every_retrieved_case_carries_its_source():
    index = rs.build_index([_mimic_record(30000001, "chest pain"), _ktas_record(5, "chest pain")])
    assert index.multi_source and index.source_counts == {"MIMIC-IV-ED": 1, "KTAS": 1}
    cases = rs.find_similar_cases(None, "I have chest pain", index=index)
    assert {c.source for c in cases} == {"MIMIC-IV-ED", "KTAS"}
    refs = {c.case_ref for c in cases}
    assert refs == {30000001, "KTAS-5"}
    text = rs.format_cases_as_context(cases)
    assert text.count("Source: ") == len(cases)
    assert "Source: KTAS | Chief Complaint" in text and "Source: MIMIC-IV-ED | Chief Complaint" in text


def test_single_source_evidence_text_is_unchanged():
    """MIMIC-only (and KTAS-only) knowledge bases produce exactly the pre-change evidence text (cache keys stable)."""
    for rec in (_mimic_record(30000001, "chest pain"), _ktas_record(5, "chest pain")):
        cases = rs.find_similar_cases(None, "chest pain", index=rs.build_index([rec]))
        text = rs.format_cases_as_context(cases)
        assert text.startswith('1. Chief Complaint: "chest pain" | ')
        assert "Source:" not in text


def test_record_ids_may_not_collide_across_sources():
    with pytest.raises(ValueError):
        rs.build_index([_mimic_record(7, "chest pain"), _ktas_record(7, "headache")])


def test_live_kb_adds_all_ktas_records(db, monkeypatch):
    ktas = rs.load_ktas_kb_records()
    assert len(ktas) == 1267 and {r.source for r in ktas} == {"KTAS"}
    monkeypatch.setattr(rs.settings, "KB_INCLUDE_KTAS", False)
    mimic_only = rs.live_records(db)
    monkeypatch.setattr(rs.settings, "KB_INCLUDE_KTAS", True)
    both = rs.live_records(db)
    assert len(both) == len(mimic_only) + 1267
    assert {r.source for r in both} == {"MIMIC-IV-ED", "KTAS"}


def test_ktas_kb_file_matches_the_evaluation_preprocessing():
    from evaluation.data import load_ktas
    df = load_ktas()
    kb = pd.read_csv("data/external/ktas/ktas_kb.csv")
    assert list(kb["record_id"]) == list(df["stay_id"])
    assert list(kb["severity"]) == list(df["label"])
    assert "nurse_label" not in kb.columns and "KTAS_RN" not in kb.columns


def test_evaluation_kb_never_contains_ktas_validation_or_test_records():
    from evaluation.data import load_ktas
    from evaluation.llm_runner import LLMJob
    from evaluation.runner import KnowledgeBaseLeak, kb_frame
    from evaluation.splits import make_or_load, subset

    df = load_ktas()
    parts = {k: subset(df, ids) for k, ids in make_or_load(df, "ktas").items()}
    bundle = {"parts": {"ktas": parts}}
    job = LLMJob("ktas:S4:kb=mimic+ktas-train", "ktas", "S4", "mimic-all+ktas-train")
    kb = kb_frame(bundle, job)
    assert len(kb) == 886
    assert not (set(kb["case_id"]) & (set(parts["validation"]["case_id"]) | set(parts["test"]["case_id"])))
    leaky = dict(parts, train=pd.concat([parts["train"], parts["test"].head(1)]))
    with pytest.raises(KnowledgeBaseLeak):
        kb_frame({"parts": {"ktas": leaky}}, job)


def test_ktas_jobs_and_knowledge_base_guard():
    from evaluation.frozen import ConfigNotFrozen, assert_frozen, frozen_record
    from evaluation.llm_runner import LLMJob
    from evaluation.runner import LLM_JOBS

    ktas = [j for j in LLM_JOBS if j.dataset == "ktas"]
    assert ktas[0].name == "ktas:S4:kb=mimic+ktas-train" and ktas[0].split == "test"   # main job runs first
    assert ktas[1].system == "S3" and ktas[1].split == "test"
    assert not any(j.kb == "ktas-train" for j in LLM_JOBS)
    assert "knowledge_base" in frozen_record()
    for job in ktas:
        assert_frozen(job)
    with pytest.raises(ConfigNotFrozen):
        assert_frozen(LLMJob("x", "ktas", "S4", "ktas-all"))
