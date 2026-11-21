# KTAS dataset -- source record

- **Citation:** Moon, S.H., Shim, J.L., Park, K.S. and Park, C.S. (2019) 'Triage accuracy and causes of mistriage using the Korean Triage and Acuity Scale', *PLoS ONE*, 14(9), e0216972. doi:10.1371/journal.pone.0216972
- **Article page:** https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0216972
- **File used:** S1 Appendix "EMR review coding data" (XLSX), https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371/journal.pone.0216972.s001
- **Coding sheet:** S2 Appendix "EMR review coding guideline" (XLSX), https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371/journal.pone.0216972.s002
- **Downloaded:** 2026-11-21 by `python -m scripts.download_ktas`
- **SHA-256 (ktas_raw_S1.xlsx):** `f631c951178799179d0fbd74fe979464b955ea1b426222bf015b163b8a24beb0`
- **SHA-256 (ktas_raw.csv, derived):** `95d151c56a0a326d48b7e093d65792f806a245e7b3bd6c3658bf54de85d7ba94`
- **Licence as found on the article page:** Creative Commons Attribution 4.0 (CC BY 4.0) -- redistribution allowed with attribution; files committed to this repository.
- **Mirror used:** no (official journal Supporting Information).
- **Sheet:** `N=1267 data`; rows: 1267; columns: 24
- **Sites:** Group 1 = local ED (688 rows), Group 2 = regional ED (579 rows)
- **KTAS_expert counts:** 1: 26, 2: 220, 3: 487, 4: 459, 5: 75
- **3-class (expert):** High (1-2) 246, Medium (3) 487, Low (4-5) 534
- **KTAS_RN counts:** 1: 18, 2: 214, 3: 447, 4: 501, 5: 87
- **Coding (from S2):** Sex 1 = Female, 2 = Male; Arrival mode 1 walking, 2 public ambulance (119), 3 private car, 4 private ambulance, 5 public transport/police, 6 wheelchair, 7 other; Injury 1 = non-injury, 2 = injury; Mental 1 alert, 2 verbal response, 3 pain response, 4 unconscious; Pain 1 = pain, 2 = no pain; mistriage 0 correct, 1 over-triage, 2 under-triage.
- **Use in this project:** external validation only, never loaded by the live system.
