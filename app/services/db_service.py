"""
Clinical database search service.

Replaces the PoC's Pandas logic (extract keywords > 4 chars from the
transcript, filter df_final['chiefcomplaint'] by substring match, take
the top 5 rows) with an equivalent SQLAlchemy query against PostgreSQL.

The output is a plain formatted string ("db_context") because that is
what llm_service.py injects directly into the LLM's system prompt.
"""

import logging
import re
import string
from dataclasses import dataclass
from typing import List

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.mimic_models import Diagnosis, Triage

logger = logging.getLogger(__name__)
settings = get_settings()

# Common English stopwords that are technically > 4 characters but carry
# no clinical signal. Filtering these out reduces noisy/irrelevant
# keyword matches (e.g. "which", "there", "about").
_STOPWORDS = {
    "about", "after", "again", "before", "could", "every", "hours",
    "maybe", "might", "since", "still", "there", "these", "think",
    "today", "under", "where", "which", "while", "would",
}


@dataclass
class SimilarCase:
    """A single historical case retrieved as evidence for the LLM."""

    stay_id: int
    chief_complaint: str
    icd_title: str
    severity: str


def _extract_keywords(text: str, min_length: int = None) -> List[str]:
    """
    Extracts search keywords from transcribed patient speech.

    Mirrors the PoC rule: tokenize on whitespace, strip punctuation,
    keep words longer than `min_length` characters, lowercase them, and
    drop duplicates while preserving order.
    """
    min_length = min_length or settings.MIN_KEYWORD_LENGTH
    # Strip punctuation before splitting so "chest," -> "chest"
    cleaned = text.translate(str.maketrans("", "", string.punctuation))
    tokens = re.split(r"\s+", cleaned.strip().lower())

    seen = set()
    keywords: List[str] = []
    for token in tokens:
        if len(token) > min_length and token not in _STOPWORDS and token not in seen:
            seen.add(token)
            keywords.append(token)

    return keywords


def find_similar_cases(db: Session, transcribed_text: str) -> List[SimilarCase]:
    """
    Finds historical ED cases whose chief complaint matches keywords
    extracted from the patient's transcribed speech.

    Args:
        db: An active SQLAlchemy session.
        transcribed_text: The patient's transcribed speech.

    Returns:
        Up to `settings.MAX_SIMILAR_CASES` SimilarCase records, each
        paired with its most relevant diagnosis title if one exists.
        Returns an empty list if no keywords were extractable or no
        matches were found -- callers must handle this explicitly rather
        than assume evidence is always present.
    """
    keywords = _extract_keywords(transcribed_text)
    if not keywords:
        logger.warning("No usable keywords extracted from transcript: %r", transcribed_text)
        return []

    # Build an OR of ILIKE conditions, one per keyword, against the
    # chief_complaint column (case-insensitive substring match, the SQL
    # equivalent of the PoC's Python `in` check on df_final).
    conditions = [Triage.chief_complaint.ilike(f"%{kw}%") for kw in keywords]

    matched_triage_rows = (
        db.query(Triage)
        .filter(or_(*conditions))
        .order_by(Triage.id.desc())  # arbitrary stable tie-break; see note below
        .limit(settings.MAX_SIMILAR_CASES)
        .all()
    )

    results: List[SimilarCase] = []
    for triage_row in matched_triage_rows:
        # Each stay can have multiple diagnoses; take the first recorded
        # one as the representative ICD title for this evidence row.
        diagnosis = (
            db.query(Diagnosis)
            .filter(Diagnosis.stay_id == triage_row.stay_id)
            .order_by(Diagnosis.id.asc())
            .first()
        )

        results.append(
            SimilarCase(
                stay_id=triage_row.stay_id,
                chief_complaint=triage_row.chief_complaint or "Unknown",
                icd_title=(diagnosis.icd_title if diagnosis and diagnosis.icd_title else "Not recorded"),
                severity=(triage_row.severity.value if triage_row.severity else "Unknown"),
            )
        )

    return results


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
    for i, case in enumerate(cases, start=1):
        lines.append(
            f"{i}. Chief Complaint: \"{case.chief_complaint}\" | "
            f"Diagnosis: {case.icd_title} | "
            f"Recorded Severity: {case.severity}"
        )
    return "\n".join(lines)


def get_similar_cases_context(db: Session, transcribed_text: str) -> str:
    """
    Convenience entrypoint used by the API layer: runs the search and
    returns the formatted context string in a single call.
    """
    cases = find_similar_cases(db, transcribed_text)
    return format_cases_as_context(cases)
