"""
Agent 2 -- Evidence Retrieval (multi-source knowledge base).

Finds the historical cases most similar to the current patient and
returns them as grounding evidence for the LLM. Since 2026-11-22 the
knowledge base has two sources, and every retrieved case carries its
source label:

  "MIMIC-IV-ED"  ED stays from the MIMIC-IV-ED Demo (Boston, USA; ESI labels), from the database
  "KTAS"         ED records from Moon et al. (2019) (two Korean EDs; KTAS_expert labels), from
                 data/external/ktas/ktas_kb.csv (scripts/build_ktas_kb.py)

The live system uses all MIMIC stays + all KTAS records
(settings.KB_INCLUDE_KTAS); the offline evaluation builds explicit
knowledge bases from training data only (build_index).

Unlike the original PoC (a single ILIKE on chief_complaint), every stay
is scored across all six MIMIC-IV-ED tables:

  component        source tables                     default weight
  ---------------  --------------------------------  --------------
  complaint        triage.chiefcomplaint             1.0
  diagnosis        diagnosis.icd_title               0.7
  vitals           triage vitals, vitalsign (mean)   0.5  (only when vitals are supplied)
  medication       medrecon, pyxis                   0.3
  (edstays provides the stay itself and its disposition)

Text components use TF-IDF cosine similarity after clinical
normalisation: MIMIC abbreviations ("SOB", "N/V", "ABD PAIN") and lay
phrasing ("can't breathe", "stomach", "threw up") are mapped onto shared
tokens, so "I can't catch my breath" matches a historical "SOB" stay.
This is lexical similarity with a synonym layer rather than a neural
embedding model -- deliberately, so the Space stays CPU-only and every
match can be explained token by token. A complaint whose every token
appears in the patient's statement counts as an exact match (1.0).

The final score is the weighted mean of the applicable components, so
it is always in [0, 1]. The index over all stays is built once per
process (the MIMIC data is static reference data) and cached.
"""

import logging
import math
import re
import csv
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models.mimic_models import EDStay

logger = logging.getLogger(__name__)
settings = get_settings()

_STOPWORDS = {
    "the", "and", "for", "with", "have", "has", "had", "been", "this", "that",
    "about", "after", "again", "before", "could", "every", "hours", "maybe",
    "might", "since", "still", "there", "these", "think", "today", "under",
    "where", "which", "while", "would", "feel", "feeling", "really", "very",
    "some", "just", "like", "got", "get", "was", "were", "are", "not", "but",
    "you", "your", "can", "cant", "cannot", "dont", "also", "now", "day",
    "days", "week", "weeks", "since", "lot", "bit", "patient", "unspecified",
    "other", "site", "type", "without", "mention", "nos", "initial", "encounter",
}

# Phrases are rewritten before tokenising (both for patient text and
# historical records) so multi-word lay terms land on clinical tokens.
_PHRASES = [
    (r"\bn\s*/\s*v\b", " nausea vomiting "),
    (r"\bs\s*/\s*p\b", " "),
    (r"\br\s*/\s*o\b", " "),
    (r"\bshort(ness)? of breath\b", " dyspnea "),
    (r"\b(can'?t|cannot|hard to|trouble|difficulty) (catch my )?breath(e|ing)?\b", " dyspnea "),
    (r"\bthrow(ing|n)? up\b|\bthrew up\b|\bpuk(e|ed|ing)\b", " vomiting "),
    (r"\bpass(ed)? out\b|\bblack(ed)? out\b", " syncope "),
    (r"\bheart attack\b", " chest pain "),
    (r"\bcar (accident|crash)\b", " mvc "),
    (r"\bhigh (temperature|temp)\b", " fever "),
    (r"\bblood sugar\b", " hyperglycemia "),
]

# Single-token normalisation applied after tokenising.
_TOKEN_MAP: Dict[str, List[str]] = {
    "sob": ["dyspnea"], "breathless": ["dyspnea"], "breathing": ["dyspnea"],
    "breath": ["dyspnea"], "breathe": ["dyspnea"], "wheezing": ["dyspnea", "wheeze"],
    "abd": ["abdominal"], "abdomen": ["abdominal"], "stomach": ["abdominal"],
    "belly": ["abdominal"], "tummy": ["abdominal"],
    "vomit": ["vomiting"], "vomited": ["vomiting"], "nauseous": ["nausea"], "nauseated": ["nausea"],
    "dizzy": ["dizziness"], "lightheaded": ["dizziness"], "vertigo": ["dizziness"],
    "faint": ["syncope"], "fainted": ["syncope"], "fainting": ["syncope"],
    "feverish": ["fever"], "fevers": ["fever"], "febrile": ["fever"],
    "fell": ["fall"], "falling": ["fall"], "fallen": ["fall"],
    "etoh": ["alcohol"], "drunk": ["alcohol"], "intoxicated": ["alcohol"],
    "loc": ["syncope"], "unconscious": ["syncope"],
    "cp": ["chest", "pain"], "ha": ["headache"], "migraine": ["headache"],
    "uti": ["urinary", "infection"], "dysuria": ["urinary"],
    "hurts": ["pain"], "hurting": ["pain"], "ache": ["pain"], "aching": ["pain"],
    "painful": ["pain"], "sore": ["pain"],
    "bleeding": ["bleed"], "blood": ["bleed"], "hemorrhage": ["bleed"],
    "si": ["suicidal"], "suicide": ["suicidal"],
    "seizures": ["seizure"], "fitting": ["seizure"], "convulsion": ["seizure"],
    "swollen": ["swelling"], "edema": ["swelling"],
    "diarrhoea": ["diarrhea"], "cough": ["cough"], "coughing": ["cough"],
    "weak": ["weakness"], "tired": ["fatigue"], "exhausted": ["fatigue"],
    "confused": ["confusion"], "ams": ["confusion"],
    "palpitation": ["palpitations"], "racing": ["palpitations"],
}

# Typical clinical spread used to turn vital-sign differences into a
# similarity in (0, 1]: a difference of one scale unit gives ~0.37.
_VITAL_SCALES = {
    "temperature": 2.0, "heart_rate": 25.0, "resp_rate": 6.0,
    "o2sat": 4.0, "sbp": 25.0, "dbp": 15.0,
}

_MIN_SCORE = 0.05

SOURCE_MIMIC = "MIMIC-IV-ED"
SOURCE_KTAS = "KTAS"


@dataclass
class SimilarCase:
    """A single historical case retrieved as evidence for the LLM."""

    stay_id: int
    chief_complaint: str
    icd_title: str
    severity: str
    diagnoses: List[str] = field(default_factory=list)
    vitals: Dict[str, Optional[float]] = field(default_factory=dict)
    treatments: List[str] = field(default_factory=list)
    disposition: Optional[str] = None
    similarity_score: float = 0.0
    source: str = SOURCE_MIMIC
    # True when the case came from a knowledge base with more than one source; the LLM
    # evidence text then names the source of every case (single-source text is unchanged).
    multi_source_kb: bool = field(default=False, repr=False)

    @property
    def case_ref(self) -> Union[int, str]:
        """Stable reference: the MIMIC stay_id (int) or "KTAS-<record id>"."""
        return self.stay_id if self.source == SOURCE_MIMIC else f"{self.source}-{self.stay_id}"


def _normalise(text: str) -> List[str]:
    text = (text or "").lower()
    for pattern, repl in _PHRASES:
        text = re.sub(pattern, repl, text)
    tokens: List[str] = []
    for raw in re.findall(r"[a-z]+", text):
        if raw in _TOKEN_MAP:
            tokens.extend(_TOKEN_MAP[raw])
            continue
        if len(raw) < 3 or raw in _STOPWORDS:
            continue
        if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        tokens.append(raw)
    return tokens


class _TfidfField:
    """TF-IDF vectors for one text field across all indexed stays."""

    def __init__(self, docs: Dict[int, List[str]]):
        df = Counter()
        for tokens in docs.values():
            df.update(set(tokens))
        n = max(len(docs), 1)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.vectors = {sid: self._vector(tokens) for sid, tokens in docs.items()}

    def _vector(self, tokens: Iterable[str]) -> Dict[str, float]:
        tf = Counter(tokens)
        vec = {t: c * self.idf.get(t, 0.0) for t, c in tf.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return {t: v / norm for t, v in vec.items()} if norm else {}

    def similarity(self, query_tokens: List[str], stay_id: int) -> float:
        q = self._vector(query_tokens)
        d = self.vectors.get(stay_id, {})
        if not q or not d:
            return 0.0
        return sum(w * d.get(t, 0.0) for t, w in q.items())


@dataclass
class _StayRecord:
    stay_id: int
    chief_complaint: str
    complaint_tokens: List[str]
    severity: str
    diagnoses: List[str]
    vitals: Dict[str, Optional[float]]
    treatments: List[str]
    disposition: Optional[str]
    medication_text: str = ""
    source: str = SOURCE_MIMIC


class _EvidenceIndex:
    def __init__(self, records: List[_StayRecord], complaint, diagnosis, medication):
        self.records = records
        self.complaint = complaint
        self.diagnosis = diagnosis
        self.medication = medication
        self.source_counts = dict(Counter(r.source for r in records))

    @property
    def multi_source(self) -> bool:
        return len(self.source_counts) > 1


_index: Optional[_EvidenceIndex] = None
_restricted_indexes: Dict[frozenset, _EvidenceIndex] = {}
_index_lock = threading.Lock()


def invalidate_index() -> None:
    """Drops the cached indexes (call after re-importing MIMIC data, and in tests)."""
    global _index
    with _index_lock:
        _index = None
        _restricted_indexes.clear()


def _mean(values: List[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 1) if clean else None


def records_from_db(db: Session, allowed_stay_ids: Optional[Iterable[int]] = None) -> List[_StayRecord]:
    """Loads one _StayRecord per stay with a chief complaint (optionally only the given stay IDs)."""
    query = db.query(EDStay).options(
        selectinload(EDStay.triage),
        selectinload(EDStay.diagnoses),
        selectinload(EDStay.med_reconciliations),
        selectinload(EDStay.pyxis_medications),
        selectinload(EDStay.vital_signs),
    )
    if allowed_stay_ids is not None:
        query = query.filter(EDStay.stay_id.in_(list(allowed_stay_ids)))

    records: List[_StayRecord] = []
    for stay in query.all():
        triage = stay.triage
        if triage is None or not triage.chief_complaint:
            continue

        diagnoses = [d.icd_title for d in stay.diagnoses if d.icd_title]
        treatments = list(dict.fromkeys(p.name for p in stay.pyxis_medications if p.name))
        home_meds = [m.etc_description or m.name for m in stay.med_reconciliations if (m.etc_description or m.name)]

        # Prefer the triage-time snapshot; fall back to the mean of the
        # time-series vitals when triage vitals were not recorded.
        vitals = {}
        for name in _VITAL_SCALES:
            value = getattr(triage, name, None)
            if value is None:
                value = _mean([getattr(v, name, None) for v in stay.vital_signs])
            vitals[name] = value

        records.append(
            _StayRecord(
                stay_id=stay.stay_id,
                chief_complaint=triage.chief_complaint,
                complaint_tokens=_normalise(triage.chief_complaint),
                severity=triage.severity.value if triage.severity else "Unknown",
                diagnoses=diagnoses,
                vitals=vitals,
                treatments=treatments,
                disposition=stay.disposition,
                medication_text=" ".join(treatments + home_meds),
            )
        )
    return records


def ktas_record(record_id: int, complaint: str, severity: str, diagnosis: Optional[str],
                vitals: Dict[str, Optional[float]], disposition: Optional[str]) -> _StayRecord:
    """One KTAS record as knowledge-base evidence (no medication data in KTAS)."""
    return _StayRecord(
        stay_id=int(record_id),
        chief_complaint=complaint,
        complaint_tokens=_normalise(complaint),
        severity=severity,
        diagnoses=[diagnosis] if diagnosis else [],
        vitals={k: vitals.get(k) for k in _VITAL_SCALES},
        treatments=[],
        disposition=disposition or None,
        medication_text="",
        source=SOURCE_KTAS,
    )


def _float_or_none(value: str) -> Optional[float]:
    try:
        return float(value) if value not in ("", None) else None
    except ValueError:
        return None


def load_ktas_kb_records(path: Optional[Union[str, Path]] = None,
                         allowed_record_ids: Optional[Iterable[int]] = None) -> List[_StayRecord]:
    """Reads the preprocessed KTAS knowledge-base CSV (scripts/build_ktas_kb.py)."""
    path = Path(path or settings.KTAS_KB_PATH)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    if not path.exists():
        logger.warning("KTAS knowledge-base file %s not found; using MIMIC-IV-ED only.", path)
        return []
    allowed = None if allowed_record_ids is None else {int(i) for i in allowed_record_ids}
    records = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rid = int(row["record_id"])
            if allowed is not None and rid not in allowed:
                continue
            records.append(ktas_record(rid, row["complaint"], row["severity"], row.get("diagnosis") or None,
                                       {k: _float_or_none(row.get(k, "")) for k in _VITAL_SCALES},
                                       row.get("disposition") or None))
    return records


def build_index(records: List[_StayRecord]) -> _EvidenceIndex:
    """
    Builds the TF-IDF evidence index from an explicit list of records.

    Used by the offline evaluation to build a knowledge base from the
    training split only (so a test case can never retrieve itself), and by
    the KTAS in-domain setting where records come from KTAS-train.
    """
    keys = [(r.source, r.stay_id) for r in records]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate (source, id) in knowledge base")
    if len({r.stay_id for r in records}) != len(records):
        raise ValueError("record ids collide across sources")
    complaint_docs, diagnosis_docs, medication_docs = {}, {}, {}
    for rec in records:
        if not rec.complaint_tokens:
            rec.complaint_tokens = _normalise(rec.chief_complaint)
        complaint_docs[rec.stay_id] = rec.complaint_tokens
        diagnosis_docs[rec.stay_id] = _normalise(" ".join(rec.diagnoses))
        medication_docs[rec.stay_id] = _normalise(rec.medication_text or " ".join(rec.treatments))
    logger.info("Built evidence index over %d historical cases (%s).", len(records),
                dict(Counter(r.source for r in records)))
    return _EvidenceIndex(
        records,
        _TfidfField(complaint_docs),
        _TfidfField(diagnosis_docs),
        _TfidfField(medication_docs),
    )


def live_records(db: Session) -> List[_StayRecord]:
    """Live knowledge base: all MIMIC-IV-ED stays + (KB_INCLUDE_KTAS) all KTAS records."""
    records = records_from_db(db)
    if settings.KB_INCLUDE_KTAS:
        records += load_ktas_kb_records()
    return records


def _build_index(db: Session) -> _EvidenceIndex:
    return build_index(live_records(db))


def knowledge_base_summary(db: Session) -> Dict[str, int]:
    """Number of indexed cases per source in the live knowledge base."""
    return dict(_get_index(db).source_counts)


def _get_restricted_index(db: Session, allowed_stay_ids: Iterable[int]) -> _EvidenceIndex:
    key = frozenset(int(s) for s in allowed_stay_ids)
    with _index_lock:
        index = _restricted_indexes.get(key)
    if index is None:
        index = build_index(records_from_db(db, key))
        with _index_lock:
            _restricted_indexes[key] = index
    return index


def _get_index(db: Session) -> _EvidenceIndex:
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                _index = _build_index(db)
    return _index


def _vitals_similarity(query: Dict[str, Optional[float]], case: Dict[str, Optional[float]]) -> Optional[float]:
    sims = []
    for name, scale in _VITAL_SCALES.items():
        q, c = query.get(name), case.get(name)
        if q is None or c is None:
            continue
        sims.append(math.exp(-(((q - c) / scale) ** 2)))
    return sum(sims) / len(sims) if sims else None


def find_similar_cases(
    db: Session,
    transcribed_text: str,
    vitals: Optional[Dict[str, Optional[float]]] = None,
    limit: Optional[int] = None,
    allowed_stay_ids: Optional[Iterable[int]] = None,
    index: Optional[_EvidenceIndex] = None,
    weights: Optional[Dict[str, float]] = None,
) -> List[SimilarCase]:
    """
    Scores every indexed historical stay against the patient and returns
    the top matches, best first.

    Args:
        db: An active SQLAlchemy session.
        transcribed_text: The patient's transcribed speech or typed complaint.
        vitals: Optional current vitals (keys as in VitalsInput).
        limit: Max cases to return (default settings.MAX_SIMILAR_CASES).
        allowed_stay_ids: Optional leakage control -- search only these
            historical stays (the evaluation passes the training split).
            When omitted, the full production index is used (unchanged).
        index: Optional prebuilt index (see build_index); overrides the above.
        weights: Optional override of the RETRIEVAL_WEIGHT_* settings, keys
            complaint/diagnosis/vitals/medication (used for tuning).

    Returns:
        Up to `limit` SimilarCase records with a similarity_score in [0, 1].
        Empty if nothing scored above the noise floor -- callers must
        handle that explicitly rather than assume evidence is present.
    """
    limit = limit or settings.MAX_SIMILAR_CASES
    query_tokens = _normalise(transcribed_text)
    query_vitals = {k: v for k, v in (vitals or {}).items() if v is not None}
    if not query_tokens and not query_vitals:
        logger.warning("No usable keywords or vitals in patient input: %r", transcribed_text)
        return []

    if index is None:
        index = _get_restricted_index(db, allowed_stay_ids) if allowed_stay_ids is not None else _get_index(db)
    query_token_set = set(query_tokens)
    w = weights or {}
    w_complaint = w.get("complaint", settings.RETRIEVAL_WEIGHT_COMPLAINT)
    w_diagnosis = w.get("diagnosis", settings.RETRIEVAL_WEIGHT_DIAGNOSIS)
    w_vitals = w.get("vitals", settings.RETRIEVAL_WEIGHT_VITALS)
    w_medication = w.get("medication", settings.RETRIEVAL_WEIGHT_MEDICATION)

    scored = []
    for rec in index.records:
        if rec.complaint_tokens and set(rec.complaint_tokens) <= query_token_set:
            complaint_sim = 1.0  # exact match: every complaint token was said by the patient
        else:
            complaint_sim = index.complaint.similarity(query_tokens, rec.stay_id)
        diagnosis_sim = index.diagnosis.similarity(query_tokens, rec.stay_id)
        medication_sim = index.medication.similarity(query_tokens, rec.stay_id)

        total = w_complaint * complaint_sim + w_diagnosis * diagnosis_sim + w_medication * medication_sim
        weight_sum = w_complaint + w_diagnosis + w_medication
        # Only text fields that carry weight count as evidence of a match.
        text_signal = (complaint_sim if w_complaint else 0.0) + (diagnosis_sim if w_diagnosis else 0.0)             + (medication_sim if w_medication else 0.0)

        vitals_sim = _vitals_similarity(query_vitals, rec.vitals) if query_vitals else None
        if vitals_sim is not None:
            total += w_vitals * vitals_sim
            weight_sum += w_vitals

        # Vitals alone are not evidence of a similar presentation unless the
        # patient gave us no usable text at all.
        if query_tokens and text_signal == 0.0:
            continue
        score = total / weight_sum if weight_sum else 0.0
        if score >= _MIN_SCORE:
            scored.append((score, rec))

    scored.sort(key=lambda item: (-item[0], item[1].stay_id))
    return [
        SimilarCase(
            stay_id=rec.stay_id,
            chief_complaint=rec.chief_complaint,
            icd_title=rec.diagnoses[0] if rec.diagnoses else "Not recorded",
            severity=rec.severity,
            diagnoses=rec.diagnoses[:5],
            vitals=rec.vitals,
            treatments=rec.treatments[:5],
            disposition=rec.disposition,
            similarity_score=round(score, 3),
            source=rec.source,
            multi_source_kb=index.multi_source,
        )
        for score, rec in scored[:limit]
    ]


def _fmt_vitals(vitals: Dict[str, Optional[float]]) -> str:
    labels = {"heart_rate": "HR", "resp_rate": "RR", "o2sat": "SpO2", "sbp": "SBP", "dbp": "DBP", "temperature": "Temp"}
    parts = [f"{labels[k]} {v:g}" for k, v in vitals.items() if v is not None and k in labels]
    return ", ".join(parts) if parts else "not recorded"


def format_cases_as_context(cases: List[SimilarCase]) -> str:
    """
    Formats retrieved cases into a plain-text block suitable for
    injection into the LLM system prompt.

    Returns an explicit "no evidence found" message rather than an empty
    string when `cases` is empty, so the LLM prompt never silently
    receives blank context.
    """
    if not cases:
        return "No matching historical cases were found in the database for this complaint."

    lines = []
    show_source = any(c.multi_source_kb for c in cases)
    for i, case in enumerate(cases, start=1):
        lines.append(
            f"{i}. " + (f"Source: {case.source} | " if show_source else "") + f"Chief Complaint: \"{case.chief_complaint}\" | "
            f"Diagnoses: {'; '.join(case.diagnoses) or case.icd_title} | "
            f"Vitals: {_fmt_vitals(case.vitals)} | "
            f"ED Treatments: {', '.join(case.treatments) or 'none recorded'} | "
            f"Disposition: {case.disposition or 'unknown'} | "
            f"Recorded Severity: {case.severity} | "
            f"Similarity: {case.similarity_score:.2f}"
        )
    return "\n".join(lines)


def get_similar_cases_context(db: Session, transcribed_text: str) -> str:
    """
    Convenience entrypoint used by the API layer: runs the search and
    returns the formatted context string in a single call.
    """
    cases = find_similar_cases(db, transcribed_text)
    return format_cases_as_context(cases)


def assess_evidence(
    cases: List[SimilarCase],
    threshold: Optional[float] = None,
    min_agreement: Optional[float] = None,
) -> Dict:
    """
    WP2 -- evidence strength of a retrieval result.

    - top_similarity: similarity of the best case (0 when nothing was found)
    - mean_similarity: mean similarity of the returned top-k cases
    - label_agreement: share of the top-k cases whose recorded severity is
      the most common one among them
    Rule (threshold T = LOW_EVIDENCE_THRESHOLD, tuned on the MIMIC
    validation split, see evaluation/results/metrics.json):
      weak      top_similarity < T (or no cases)
      strong    top_similarity >= T and mean_similarity >= T and label_agreement >= min_agreement
      moderate  otherwise
    low_evidence is True exactly when the strength is "weak".
    """
    threshold = settings.LOW_EVIDENCE_THRESHOLD if threshold is None else threshold
    min_agreement = settings.EVIDENCE_MIN_AGREEMENT if min_agreement is None else min_agreement
    if not cases:
        return {"evidence_strength": "weak", "low_evidence": True, "top_similarity": 0.0,
                "mean_similarity": 0.0, "label_agreement": 0.0, "threshold": threshold}
    scores = [c.similarity_score for c in cases]
    top, mean = max(scores), sum(scores) / len(scores)
    labels = Counter(c.severity for c in cases)
    agreement = labels.most_common(1)[0][1] / len(cases)
    if top < threshold:
        strength = "weak"
    elif mean >= threshold and agreement >= min_agreement:
        strength = "strong"
    else:
        strength = "moderate"
    return {
        "evidence_strength": strength,
        "low_evidence": strength == "weak",
        "top_similarity": round(top, 3),
        "mean_similarity": round(mean, 3),
        "label_agreement": round(agreement, 3),
        "threshold": threshold,
    }
