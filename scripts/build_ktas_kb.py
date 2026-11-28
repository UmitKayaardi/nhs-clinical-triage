"""
Builds the KTAS part of the live multi-source knowledge base (Agent 2).

Reads data/external/ktas/ktas_raw.csv through the same preprocessing as the
evaluation (evaluation/data.py::load_ktas: Korean complaint translation,
vital-sign cleaning, deg C -> deg F, KTAS_expert -> High/Medium/Low) and writes
data/external/ktas/ktas_kb.csv, which app/services/retrieval_service.py loads
when KB_INCLUDE_KTAS is true. Only knowledge-base fields are written: the
complaint, recorded severity (KTAS_expert), ED diagnosis, vitals and
disposition. The nurse label (KTAS_RN) is not part of the knowledge base.

The live system uses ALL KTAS records. The offline evaluation never reads
this file; it builds its knowledge base from the KTAS training split only.

Usage:  python scripts/build_ktas_kb.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.common import VITAL_KEYS  # noqa: E402
from evaluation.data import load_ktas  # noqa: E402

OUT = ROOT / "data" / "external" / "ktas" / "ktas_kb.csv"


def main() -> None:
    df = load_ktas()
    out = df[["stay_id", "complaint", "label", "diagnosis_ed", "disposition", *VITAL_KEYS]].rename(
        columns={"stay_id": "record_id", "label": "severity", "diagnosis_ed": "diagnosis"})
    for k in VITAL_KEYS:
        out[k] = out[k].round(2)
    out.to_csv(OUT, index=False, encoding="utf-8", lineterminator="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} KTAS records "
          f"({out['severity'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
