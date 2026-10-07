"""
SQLAlchemy ORM models for the NHS Triage Assistant.

This schema replaces the single Pandas DataFrame (df_final) used in the PoC.
Instead of merging all 6 MIMIC-IV-ED CSVs (triage, diagnosis, edstays,
medrecon, pyxis, vitalsign) into one flat table, the data is normalized
around a central `EDStay` entity, matching the original relational
structure of the source data.

Design notes:
- `stay_id` is the natural key shared across all MIMIC-IV-ED tables and is
  used here as the primary linking column (kept as the PK on EDStay and as
  a FK everywhere else), so the mapping to the source CSVs stays obvious.
- `Diagnosis` and `VitalSign` are one-to-many relative to a stay (a single
  ED visit can have multiple ICD codes and multiple vitals readings over
  time). Denormalizing these into one row per stay, as the Pandas PoC did,
  would silently duplicate stay-level fields (chief complaint, acuity) and
  break aggregate queries.
- `severity` on the Triage model is a derived, stored value (not
  recomputed in application code on every query). It is calculated once
  at ingestion time from `acuity` using the same mapping as the PoC:
    acuity 1.0, 2.0 -> High
    acuity 3.0      -> Medium
    acuity 4.0, 5.0 -> Low
  Storing it (rather than deriving it in Python each time) allows
  `db_service.py` to filter and index directly on severity in SQL.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    Enum as SAEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class SeverityLevel(str, enum.Enum):
    """
    Severity classification derived from the ESI acuity score.
    Kept as a Python enum so the same values are enforced at the DB level
    (via SQLAlchemy Enum) and reused directly in Pydantic schemas /
    the LLM service's forced-JSON output.
    """

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


def map_acuity_to_severity(acuity: float) -> SeverityLevel:
    """
    Reproduces the PoC's severity mapping rule.
    Centralized here so ingestion scripts and any backfill logic use
    a single source of truth instead of duplicating the if/else mapping.
    """
    if acuity in (1.0, 2.0):
        return SeverityLevel.HIGH
    if acuity == 3.0:
        return SeverityLevel.MEDIUM
    if acuity in (4.0, 5.0):
        return SeverityLevel.LOW
    raise ValueError(f"Unmapped acuity value: {acuity}")


class EDStay(Base):
    """
    Central entity for one Emergency Department visit.
    Corresponds to the `edstays` CSV. All other tables link back to this
    via stay_id, mirroring how the source data was originally structured
    before the PoC flattened it with pandas.merge().
    """

    __tablename__ = "ed_stays"

    stay_id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, nullable=False, index=True)
    hadm_id = Column(Integer, nullable=True)

    intime = Column(DateTime, nullable=True)
    outtime = Column(DateTime, nullable=True)
    gender = Column(String(1), nullable=True)
    race = Column(String(100), nullable=True)
    arrival_transport = Column(String(50), nullable=True)
    disposition = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    triage = relationship("Triage", back_populates="stay", uselist=False, cascade="all, delete-orphan")
    diagnoses = relationship("Diagnosis", back_populates="stay", cascade="all, delete-orphan")
    med_reconciliations = relationship("MedReconciliation", back_populates="stay", cascade="all, delete-orphan")
    pyxis_medications = relationship("PyxisMedication", back_populates="stay", cascade="all, delete-orphan")
    vital_signs = relationship("VitalSign", back_populates="stay", cascade="all, delete-orphan")


class Triage(Base):
    """
    Corresponds to the `triage` CSV.
    One-to-one with EDStay: each visit has exactly one initial triage
    assessment, containing the chief complaint, ESI acuity score, and
    first-recorded vitals used to prioritize the patient.
    """

    __tablename__ = "triage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stay_id = Column(Integer, ForeignKey("ed_stays.stay_id"), nullable=False, unique=True, index=True)

    chief_complaint = Column(Text, nullable=False, index=True)
    acuity = Column(Float, nullable=True)
    severity = Column(SAEnum(SeverityLevel), nullable=True, index=True)  # derived from acuity, see map_acuity_to_severity

    # Vitals recorded at triage time (first reading, distinct from the
    # time-series vitals in VitalSign)
    temperature = Column(Float, nullable=True)
    heart_rate = Column(Float, nullable=True)
    resp_rate = Column(Float, nullable=True)
    o2sat = Column(Float, nullable=True)
    sbp = Column(Float, nullable=True)
    dbp = Column(Float, nullable=True)
    pain = Column(String(10), nullable=True)  # MIMIC stores this as free text/numeric string

    stay = relationship("EDStay", back_populates="triage")

    __table_args__ = (
        # Supports the keyword search in db_service.py (ILIKE / full-text on chief_complaint)
        Index("ix_triage_chief_complaint_gin", "chief_complaint"),
    )


class Diagnosis(Base):
    """
    Corresponds to the `diagnosis` CSV.
    One-to-many with EDStay: a single visit can be assigned multiple
    ICD-9/ICD-10 diagnosis codes and titles.
    """

    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stay_id = Column(Integer, ForeignKey("ed_stays.stay_id"), nullable=False, index=True)

    icd_code = Column(String(20), nullable=True)
    icd_version = Column(Integer, nullable=True)
    icd_title = Column(Text, nullable=True)

    stay = relationship("EDStay", back_populates="diagnoses")


class MedReconciliation(Base):
    """
    Corresponds to the `medrecon` CSV.
    Medications the patient reports taking prior to arrival (home
    medication list), captured during reconciliation. One-to-many per stay.
    """

    __tablename__ = "med_reconciliations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stay_id = Column(Integer, ForeignKey("ed_stays.stay_id"), nullable=False, index=True)

    name = Column(Text, nullable=True)
    gsn = Column(String(20), nullable=True)  # Generic Sequence Number
    ndc = Column(String(20), nullable=True)  # National Drug Code
    etc_description = Column(Text, nullable=True)

    stay = relationship("EDStay", back_populates="med_reconciliations")


class PyxisMedication(Base):
    """
    Corresponds to the `pyxis` CSV.
    Medications actually administered/dispensed during the ED visit via
    the Pyxis automated dispensing system. One-to-many per stay.
    """

    __tablename__ = "pyxis_medications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stay_id = Column(Integer, ForeignKey("ed_stays.stay_id"), nullable=False, index=True)

    name = Column(Text, nullable=True)
    gsn_rn = Column(Integer, nullable=True)
    charttime = Column(DateTime, nullable=True)

    stay = relationship("EDStay", back_populates="pyxis_medications")


class VitalSign(Base):
    """
    Corresponds to the `vitalsign` CSV.
    Time-series vitals recorded throughout the ED stay (distinct from the
    single triage-time snapshot on the Triage model). One-to-many per stay.
    """

    __tablename__ = "vital_signs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stay_id = Column(Integer, ForeignKey("ed_stays.stay_id"), nullable=False, index=True)

    charttime = Column(DateTime, nullable=True)
    temperature = Column(Float, nullable=True)
    heart_rate = Column(Float, nullable=True)
    resp_rate = Column(Float, nullable=True)
    o2sat = Column(Float, nullable=True)
    sbp = Column(Float, nullable=True)
    dbp = Column(Float, nullable=True)
    pain = Column(String(50), nullable=True)
    rhythm = Column(String(50), nullable=True)

    stay = relationship("EDStay", back_populates="vital_signs")


class TriageSession(Base):
    """
    NEW entity, not present in the original MIMIC-IV-ED CSVs.
    Represents one real-world use of the assistant: a patient's audio
    recording, its transcription, and the resulting LLM-generated triage
    report. This is what /process-triage will write to, giving you an
    audit trail distinct from the historical MIMIC reference data used
    only for similarity search.
    """

    __tablename__ = "triage_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    transcript = Column(Text, nullable=False)

    # Raw LLM output, stored for audit/debugging even though the
    # structured fields below are also extracted from it.
    llm_raw_response = Column(Text, nullable=True)

    symptoms = Column(Text, nullable=True)              # stored as JSON-encoded list
    duration = Column(String(255), nullable=True)
    possible_conditions = Column(Text, nullable=True)   # stored as JSON-encoded list
    severity = Column(SAEnum(SeverityLevel), nullable=True)

    # Which historical stay_ids were used as evidence for this report,
    # stored as a JSON-encoded list of ints. Keeping this is what lets you
    # prove the "no guessing" constraint: every session must be traceable
    # back to the specific historical cases the LLM was shown.
    evidence_stay_ids = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
