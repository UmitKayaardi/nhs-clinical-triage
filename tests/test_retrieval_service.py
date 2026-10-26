"""Agent 2 -- multi-table evidence retrieval."""

from app.services.retrieval_service import _normalise, find_similar_cases, format_cases_as_context


def test_lay_language_maps_onto_mimic_abbreviations():
    assert "dyspnea" in _normalise("I can't catch my breath")
    assert "dyspnea" in _normalise("SOB")
    assert {"nausea", "vomiting"} <= set(_normalise("Abd pain, N/V"))
    assert "abdominal" in _normalise("my stomach hurts")


def test_exact_complaint_match_ranks_first_and_scores_in_unit_range(db):
    cases = find_similar_cases(db, "I have really bad chest pain")
    assert cases[0].stay_id == 1
    assert all(0.0 < c.similarity_score <= 1.0 for c in cases)
    assert cases == sorted(cases, key=lambda c: -c.similarity_score)


def test_returns_all_tables_for_each_case(db):
    case = find_similar_cases(db, "chest pain")[0]
    assert "Acute myocardial infarction" in case.diagnoses   # diagnosis.csv
    assert "Aspirin" in case.treatments                      # pyxis.csv
    assert case.vitals["heart_rate"] == 110                  # triage / vitalsign
    assert case.disposition == "HOME"                        # edstays.csv
    assert case.severity == "High"


def test_diagnosis_only_match_scores_below_exact_complaint_match(db):
    # "sepsis" appears only in stay 7's diagnoses, never in a chief complaint.
    sepsis = find_similar_cases(db, "they said it might be sepsis")
    assert sepsis and sepsis[0].stay_id == 7
    exact = find_similar_cases(db, "hypotension")
    assert exact[0].stay_id == 7
    assert exact[0].similarity_score > sepsis[0].similarity_score


def test_medication_history_is_searchable(db):
    cases = find_similar_cases(db, "I take warfarin")
    assert cases[0].stay_id == 4


def test_vitals_reorder_otherwise_similar_cases(db):
    # Both stay 1 (chest pain) and stay 2 (dyspnea) are High; vitals that look
    # like stay 2 (hypoxic, tachypnoeic) should pull it above stay 1 when the
    # text is ambiguous between them.
    text = "chest tight and short of breath"
    hypoxic = {"o2sat": 86, "resp_rate": 28, "heart_rate": 118}
    ranked = [c.stay_id for c in find_similar_cases(db, text, vitals=hypoxic)]
    assert ranked.index(2) < ranked.index(1)


def test_no_signal_returns_empty_and_context_says_so(db):
    assert find_similar_cases(db, "hello there") == []
    assert "No matching historical cases" in format_cases_as_context([])


def test_limit_and_context_format(db):
    cases = find_similar_cases(db, "pain", limit=2)
    assert len(cases) == 2
    context = format_cases_as_context(cases)
    assert context.startswith("1. Chief Complaint:")
    assert "Similarity:" in context and "ED Treatments:" in context
