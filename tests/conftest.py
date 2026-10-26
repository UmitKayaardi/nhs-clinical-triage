"""
Shared pytest fixtures.

Environment is configured *before* any `app` module is imported, because
Settings and the SQLAlchemy engine are created at import time:
- a throwaway SQLite file database (never the committed triage_data.db);
- Twilio forced into test mode, so no real WhatsApp is ever sent;
- the admin key disabled (individual tests enable it explicitly).

Whisper is replaced with a stub module so the suite runs without torch;
every test that needs a transcript mocks audio_service.transcribe_audio.
"""

import os
import sys
import tempfile
import types
from datetime import datetime

_TMP_DIR = tempfile.mkdtemp(prefix="nhs_triage_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'test.db')}"
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["TWILIO_TEST_MODE"] = "true"
os.environ["ADMIN_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["AUDIO_TEMP_DIR"] = os.path.join(_TMP_DIR, "audio")

sys.modules.setdefault("whisper", types.SimpleNamespace(load_model=lambda *a, **k: None))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.mimic_models import (  # noqa: E402
    Diagnosis,
    EDStay,
    MedReconciliation,
    PyxisMedication,
    SeverityLevel,
    Triage,
    VitalSign,
)
from app.services import retrieval_service  # noqa: E402

# (stay_id, gender, race, complaint, severity, vitals(temp, hr, rr, o2, sbp, dbp), diagnoses, pyxis, home meds)
MIMIC_SAMPLE = [
    (1, "M", "WHITE", "Chest pain", SeverityLevel.HIGH, (98.1, 110, 20, 95, 150, 90),
     ["Other chest pain", "Acute myocardial infarction"], ["Aspirin", "Nitroglycerin SL"], ["Atorvastatin"]),
    (2, "F", "BLACK/AFRICAN AMERICAN", "Dyspnea", SeverityLevel.HIGH, (99.0, 118, 28, 86, 130, 80),
     ["Dyspnea, unspecified", "Pneumonia"], ["Albuterol neb", "Ceftriaxone"], ["Albuterol inhaler"]),
    (3, "F", "WHITE", "Abd pain, N/V", SeverityLevel.MEDIUM, (99.5, 95, 18, 99, 120, 75),
     ["Unspecified abdominal pain"], ["Ondansetron", "Morphine"], []),
    (4, "M", "HISPANIC/LATINO", "S/P FALL", SeverityLevel.MEDIUM, (98.0, 80, 16, 98, 140, 85),
     ["Head injury, unspecified", "Unspecified fall"], ["Acetaminophen"], ["Warfarin"]),
    (5, "F", "ASIAN", "Sore throat", SeverityLevel.LOW, (99.8, 85, 16, 99, 118, 72),
     ["Acute pharyngitis"], ["Ibuprofen"], []),
    (6, "M", "WHITE", "Ankle pain", SeverityLevel.LOW, (98.4, 72, 14, 100, 125, 78),
     ["Sprain of ankle"], ["Ibuprofen"], []),
    (7, "F", "WHITE", "Hypotension", SeverityLevel.HIGH, (97.0, 120, 22, 94, 82, 50),
     ["Sepsis", "Hypotension"], ["Norepinephrine", "Vancomycin"], ["Metformin"]),
    (8, "M", "BLACK/AFRICAN AMERICAN", "Headache", SeverityLevel.MEDIUM, (98.6, 78, 16, 99, 160, 95),
     ["Headache"], ["Acetaminophen", "Metoclopramide"], ["Lisinopril"]),
]


def seed_mimic(db) -> None:
    for sid, gender, race, complaint, severity, vitals, dxs, pyxis, home in MIMIC_SAMPLE:
        temp, hr, rr, o2, sbp, dbp = vitals
        db.add(EDStay(stay_id=sid, subject_id=1000 + sid, gender=gender, race=race, disposition="HOME",
                      intime=datetime(2125, 1, 1)))
        db.add(Triage(stay_id=sid, chief_complaint=complaint, severity=severity, acuity=None,
                      temperature=temp, heart_rate=hr, resp_rate=rr, o2sat=o2, sbp=sbp, dbp=dbp))
        for title in dxs:
            db.add(Diagnosis(stay_id=sid, icd_title=title))
        for name in pyxis:
            db.add(PyxisMedication(stay_id=sid, name=name))
        for name in home:
            db.add(MedReconciliation(stay_id=sid, name=name))
        db.add(VitalSign(stay_id=sid, heart_rate=hr, o2sat=o2))
    db.commit()


@pytest.fixture(autouse=True)
def fresh_database():
    """Every test starts from an empty schema with the small MIMIC sample loaded."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    retrieval_service.invalidate_index()
    db = SessionLocal()
    seed_mimic(db)
    db.close()
    yield
    retrieval_service.invalidate_index()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
