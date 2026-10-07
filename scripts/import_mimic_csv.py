"""
One-off ETL script: imports the 6 MIMIC-IV-ED demo CSV files into the
normalized PostgreSQL schema defined in app/models/mimic_models.py.

Replaces the PoC's `pandas.merge()` step. Pandas is still used here
purely as a CSV reader/cleaner -- the merged DataFrame (df_final) is
never built; each CSV is mapped independently onto its corresponding
SQLAlchemy model and written straight to the database.

Import order matters: EDStay must be loaded first, since every other
table has a foreign key on stay_id. Rows in the child CSVs that
reference a stay_id not present in edstays.csv are skipped and logged,
rather than causing the whole import to fail.

Usage:
    python -m scripts.import_mimic_csv --data-dir /path/to/mimic-iv-ed-csvs

Expected files in --data-dir:
    edstays.csv, triage.csv, diagnosis.csv, medrecon.csv, pyxis.csv, vitalsign.csv
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Set

import pandas as pd
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.mimic_models import (
    Diagnosis,
    EDStay,
    MedReconciliation,
    PyxisMedication,
    Triage,
    VitalSign,
    map_acuity_to_severity,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("import_mimic_csv")

BATCH_SIZE = 1000

# Columns across all 6 CSVs that represent timestamps and must be parsed
# into real Python datetime objects -- passing raw date strings straight
# through to SQLAlchemy DateTime columns works on some DB drivers but
# fails hard on others (e.g. SQLite), so we parse explicitly here rather
# than relying on driver-level coercion.
_DATETIME_COLUMNS = {"intime", "outtime", "charttime"}


def _load_csv(path: Path) -> pd.DataFrame:
    """
    Reads a CSV and normalizes it for ingestion:
    - Lowercases column names (MIMIC CSVs are already lowercase, but this
      guards against variant exports).
    - Replaces pandas NaN/NaT with real None so SQLAlchemy writes SQL
      NULL instead of the float NaN or the literal string "nan".
      NOTE: `df.where(pd.notnull(df), None)` alone is NOT reliable here --
      under pandas' newer string-backed dtypes it can silently leave NaN
      in place. Casting to `object` dtype first before the replacement
      avoids that.
    - Parses known timestamp columns (intime, outtime, charttime) into
      Python datetime objects.
    """
    if not path.exists():
        raise FileNotFoundError(f"Required CSV not found: {path}")

    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    for col in _DATETIME_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df = df.astype(object).where(pd.notnull(df), None)
    return df


def _to_float(value) -> Optional[float]:
    """Safely coerces a value to float, returning None for anything unparseable."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_clean_str(value) -> Optional[str]:
    """
    Coerces a value to a clean string, stripping a trailing ".0" that
    pandas introduces when a numeric-looking column (e.g. pain score,
    read as "3") gets typed as float64 because other rows are missing.
    """
    if value is None or value == "":
        return None
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _to_int(value) -> Optional[int]:
    """Safely coerces a value to int, returning None for anything unparseable."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))  # via float first, in case of "123.0"
    except (TypeError, ValueError):
        return None


def import_edstays(db: Session, df: pd.DataFrame) -> Set[int]:
    """
    Loads edstays.csv into EDStay. Returns the set of stay_ids that were
    successfully loaded, used by the child-table importers below to skip
    orphaned rows.
    """
    loaded_stay_ids: Set[int] = set()
    skipped = 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        row = row._asdict()
        stay_id = _to_int(row.get("stay_id"))
        if stay_id is None:
            skipped += 1
            continue

        stay = EDStay(
            stay_id=stay_id,
            subject_id=_to_int(row.get("subject_id")),
            hadm_id=_to_int(row.get("hadm_id")),
            intime=row.get("intime"),
            outtime=row.get("outtime"),
            gender=row.get("gender"),
            race=row.get("race"),
            arrival_transport=row.get("arrival_transport"),
            disposition=row.get("disposition"),
        )
        db.merge(stay)  # merge = upsert by primary key, safe to re-run the script
        loaded_stay_ids.add(stay_id)

        if i % BATCH_SIZE == 0:
            db.commit()
            logger.info("EDStay: committed %d rows...", i)

    db.commit()
    logger.info("EDStay import complete: %d loaded, %d skipped (missing stay_id).", len(loaded_stay_ids), skipped)
    return loaded_stay_ids


def import_triage(db: Session, df: pd.DataFrame, valid_stay_ids: Set[int]) -> None:
    """
    Loads triage.csv into Triage, computing the derived `severity` column
    from `acuity` via map_acuity_to_severity(). Rows with an
    unmappable/missing acuity are still inserted (severity=None) rather
    than dropped, since the chief complaint is still useful for search.
    """
    inserted, skipped_orphan, skipped_unmapped_acuity = 0, 0, 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        row = row._asdict()
        stay_id = _to_int(row.get("stay_id"))
        if stay_id is None or stay_id not in valid_stay_ids:
            skipped_orphan += 1
            continue

        acuity = _to_float(row.get("acuity"))
        severity = None
        if acuity is not None:
            try:
                severity = map_acuity_to_severity(acuity)
            except ValueError:
                skipped_unmapped_acuity += 1
                logger.warning("Unmapped acuity value %s for stay_id=%s; storing severity=NULL.", acuity, stay_id)

        chief_complaint = row.get("chiefcomplaint") or "Not recorded"

        triage_row = Triage(
            stay_id=stay_id,
            chief_complaint=chief_complaint,
            acuity=acuity,
            severity=severity,
            temperature=_to_float(row.get("temperature")),
            heart_rate=_to_float(row.get("heartrate")),
            resp_rate=_to_float(row.get("resprate")),
            o2sat=_to_float(row.get("o2sat")),
            sbp=_to_float(row.get("sbp")),
            dbp=_to_float(row.get("dbp")),
            pain=_to_clean_str(row.get("pain")),
        )
        db.add(triage_row)
        inserted += 1

        if i % BATCH_SIZE == 0:
            db.commit()
            logger.info("Triage: committed %d rows...", i)

    db.commit()
    logger.info(
        "Triage import complete: %d inserted, %d skipped (orphan stay_id), %d with unmapped acuity.",
        inserted, skipped_orphan, skipped_unmapped_acuity,
    )


def import_diagnosis(db: Session, df: pd.DataFrame, valid_stay_ids: Set[int]) -> None:
    """Loads diagnosis.csv into Diagnosis (one-to-many per stay)."""
    inserted, skipped = 0, 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        row = row._asdict()
        stay_id = _to_int(row.get("stay_id"))
        if stay_id is None or stay_id not in valid_stay_ids:
            skipped += 1
            continue

        db.add(
            Diagnosis(
                stay_id=stay_id,
                icd_code=row.get("icd_code"),
                icd_version=_to_int(row.get("icd_version")),
                icd_title=row.get("icd_title"),
            )
        )
        inserted += 1

        if i % BATCH_SIZE == 0:
            db.commit()
            logger.info("Diagnosis: committed %d rows...", i)

    db.commit()
    logger.info("Diagnosis import complete: %d inserted, %d skipped (orphan stay_id).", inserted, skipped)


def import_medrecon(db: Session, df: pd.DataFrame, valid_stay_ids: Set[int]) -> None:
    """Loads medrecon.csv into MedReconciliation (home medications reported at intake)."""
    inserted, skipped = 0, 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        row = row._asdict()
        stay_id = _to_int(row.get("stay_id"))
        if stay_id is None or stay_id not in valid_stay_ids:
            skipped += 1
            continue

        db.add(
            MedReconciliation(
                stay_id=stay_id,
                name=row.get("name"),
                gsn=row.get("gsn"),
                ndc=row.get("ndc"),
                etc_description=row.get("etcdescription") or row.get("etc_description"),
            )
        )
        inserted += 1

        if i % BATCH_SIZE == 0:
            db.commit()
            logger.info("MedReconciliation: committed %d rows...", i)

    db.commit()
    logger.info("MedReconciliation import complete: %d inserted, %d skipped (orphan stay_id).", inserted, skipped)


def import_pyxis(db: Session, df: pd.DataFrame, valid_stay_ids: Set[int]) -> None:
    """Loads pyxis.csv into PyxisMedication (medications actually administered)."""
    inserted, skipped = 0, 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        row = row._asdict()
        stay_id = _to_int(row.get("stay_id"))
        if stay_id is None or stay_id not in valid_stay_ids:
            skipped += 1
            continue

        db.add(
            PyxisMedication(
                stay_id=stay_id,
                name=row.get("name"),
                gsn_rn=_to_int(row.get("gsn_rn")),
                charttime=row.get("charttime"),
            )
        )
        inserted += 1

        if i % BATCH_SIZE == 0:
            db.commit()
            logger.info("PyxisMedication: committed %d rows...", i)

    db.commit()
    logger.info("PyxisMedication import complete: %d inserted, %d skipped (orphan stay_id).", inserted, skipped)


def import_vitalsign(db: Session, df: pd.DataFrame, valid_stay_ids: Set[int]) -> None:
    """Loads vitalsign.csv into VitalSign (time-series vitals throughout the stay)."""
    inserted, skipped = 0, 0

    for i, row in enumerate(df.itertuples(index=False), start=1):
        row = row._asdict()
        stay_id = _to_int(row.get("stay_id"))
        if stay_id is None or stay_id not in valid_stay_ids:
            skipped += 1
            continue

        db.add(
            VitalSign(
                stay_id=stay_id,
                charttime=row.get("charttime"),
                temperature=_to_float(row.get("temperature")),
                heart_rate=_to_float(row.get("heartrate")),
                resp_rate=_to_float(row.get("resprate")),
                o2sat=_to_float(row.get("o2sat")),
                sbp=_to_float(row.get("sbp")),
                dbp=_to_float(row.get("dbp")),
                pain=_to_clean_str(row.get("pain")),
                rhythm=row.get("rhythm"),
            )
        )
        inserted += 1

        if i % BATCH_SIZE == 0:
            db.commit()
            logger.info("VitalSign: committed %d rows...", i)

    db.commit()
    logger.info("VitalSign import complete: %d inserted, %d skipped (orphan stay_id).", inserted, skipped)


def run_import(data_dir: Path) -> None:
    """Orchestrates the full import in FK-safe order."""
    # Ensure tables exist. In a real deployment this is handled by Alembic
    # migrations (see Setup Instructions); this call is a convenience
    # no-op if the tables already exist.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        logger.info("Loading CSVs from %s ...", data_dir)
        edstays_df = _load_csv(data_dir / "edstays.csv")
        triage_df = _load_csv(data_dir / "triage.csv")
        diagnosis_df = _load_csv(data_dir / "diagnosis.csv")
        medrecon_df = _load_csv(data_dir / "medrecon.csv")
        pyxis_df = _load_csv(data_dir / "pyxis.csv")
        vitalsign_df = _load_csv(data_dir / "vitalsign.csv")

        valid_stay_ids = import_edstays(db, edstays_df)
        import_triage(db, triage_df, valid_stay_ids)
        import_diagnosis(db, diagnosis_df, valid_stay_ids)
        import_medrecon(db, medrecon_df, valid_stay_ids)
        import_pyxis(db, pyxis_df, valid_stay_ids)
        import_vitalsign(db, vitalsign_df, valid_stay_ids)

        logger.info("Import finished successfully.")
    except Exception:
        db.rollback()
        logger.exception("Import failed; transaction rolled back.")
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import MIMIC-IV-ED demo CSVs into PostgreSQL.")
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory containing edstays.csv, triage.csv, diagnosis.csv, medrecon.csv, pyxis.csv, vitalsign.csv",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    if not data_dir.is_dir():
        logger.error("Data directory does not exist: %s", data_dir)
        sys.exit(1)

    run_import(data_dir)


if __name__ == "__main__":
    main()
