"""
Downloads the KTAS external-validation dataset from the source paper's own
Supporting Information (PLoS ONE, CC BY 4.0) and writes:

  data/external/ktas/ktas_raw_S1.xlsx   original file, unchanged
  data/external/ktas/ktas_coding_S2.xlsx coding sheet (variable meanings)
  data/external/ktas/ktas_raw.csv       sheet "N=1267 data" as UTF-8 CSV
  data/external/ktas/SOURCE.md          citation, URL, date, SHA-256, counts

Source: Moon, S.H., Shim, J.L., Park, K.S. and Park, C.S. (2019) 'Triage
accuracy and causes of mistriage using the Korean Triage and Acuity Scale',
PLoS ONE, 14(9), e0216972. doi:10.1371/journal.pone.0216972.

Usage: python -m scripts.download_ktas [--force]
"""

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "ktas"
ARTICLE_URL = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0216972"
S1_URL = "https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371/journal.pone.0216972.s001"
S2_URL = "https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371/journal.pone.0216972.s002"
EXPECTED_S1_SHA256 = "f631c951178799179d0fbd74fe979464b955ea1b426222bf015b163b8a24beb0"
EXPECTED_COLUMNS = [
    "Group", "Sex", "Age", "Patients number per hour", "Arrival mode", "Injury", "Chief_complain",
    "Mental", "Pain", "NRS_pain", "SBP", "DBP", "HR", "RR", "BT", "Saturation", "KTAS_RN",
    "Diagnosis in ED", "Disposition", "KTAS_expert", "Error_group", "Length of stay_min",
    "KTAS duration_min", "mistriage",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (research data download)"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, dest: Path) -> None:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--force", action="store_true", help="re-download even if files exist")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    s1, s2, csv = OUT / "ktas_raw_S1.xlsx", OUT / "ktas_coding_S2.xlsx", OUT / "ktas_raw.csv"
    if args.force or not s1.exists():
        download(S1_URL, s1)
    if args.force or not s2.exists():
        download(S2_URL, s2)

    digest = sha256(s1)
    if digest != EXPECTED_S1_SHA256:
        print(f"WARNING: SHA-256 {digest} differs from the expected {EXPECTED_S1_SHA256}")

    df = pd.read_excel(s1, sheet_name="N=1267 data", engine="openpyxl")
    if list(df.columns) != EXPECTED_COLUMNS or len(df) != 1267:
        print(f"ERROR: unexpected shape {df.shape} / columns {list(df.columns)}")
        return 1
    df.to_csv(csv, index=False, encoding="utf-8")

    def counts(col: str) -> str:
        return ", ".join(f"{k}: {v}" for k, v in df[col].value_counts().sort_index().items())

    expert = df["KTAS_expert"]
    source_md = f"""# KTAS dataset -- source record

- **Citation:** Moon, S.H., Shim, J.L., Park, K.S. and Park, C.S. (2019) 'Triage accuracy and causes of mistriage using the Korean Triage and Acuity Scale', *PLoS ONE*, 14(9), e0216972. doi:10.1371/journal.pone.0216972
- **Article page:** {ARTICLE_URL}
- **File used:** S1 Appendix "EMR review coding data" (XLSX), {S1_URL}
- **Coding sheet:** S2 Appendix "EMR review coding guideline" (XLSX), {S2_URL}
- **Downloaded:** {date.today().isoformat()} by `python -m scripts.download_ktas`
- **SHA-256 (ktas_raw_S1.xlsx):** `{digest}`
- **SHA-256 (ktas_raw.csv, derived):** `{sha256(csv)}`
- **Licence as found on the article page:** Creative Commons Attribution 4.0 (CC BY 4.0) -- redistribution allowed with attribution; files committed to this repository.
- **Mirror used:** no (official journal Supporting Information).
- **Sheet:** `N=1267 data`; rows: {len(df)}; columns: {df.shape[1]}
- **Sites:** Group 1 = local ED ({(df['Group'] == 1).sum()} rows), Group 2 = regional ED ({(df['Group'] == 2).sum()} rows)
- **KTAS_expert counts:** {counts('KTAS_expert')}
- **3-class (expert):** High (1-2) {int(expert.isin([1, 2]).sum())}, Medium (3) {int((expert == 3).sum())}, Low (4-5) {int(expert.isin([4, 5]).sum())}
- **KTAS_RN counts:** {counts('KTAS_RN')}
- **Coding (from S2):** Sex 1 = Female, 2 = Male; Arrival mode 1 walking, 2 public ambulance (119), 3 private car, 4 private ambulance, 5 public transport/police, 6 wheelchair, 7 other; Injury 1 = non-injury, 2 = injury; Mental 1 alert, 2 verbal response, 3 pain response, 4 unconscious; Pain 1 = pain, 2 = no pain; mistriage 0 correct, 1 over-triage, 2 under-triage.
- **Use in this project:** external validation only, never loaded by the live system.
"""
    (OUT / "SOURCE.md").write_text(source_md, encoding="utf-8")
    print(f"KTAS saved to {OUT} ({len(df)} rows, {df.shape[1]} columns, sha256 {digest[:12]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
