# Evaluation summary (tables only)

Protocol: MIMIC protocol v2: development set = old validation + old test splits (62 stays, 26 patients; prompt v1 -> v2 developed here, LLM-free tuning uses it); held-out test = 31 stays from 9 patients drawn from the old training patients only (never an LLM query before), evaluated once with the frozen configuration; knowledge base and ML training data for the test run = remaining 114 stays / 21 patients. KTAS: MAIN evaluation with the frozen configuration (prompt v2), never used for development: full test split (191 cases); S4 knowledge base = all MIMIC-IV-ED stays (222) + KTAS training split only (886), KTAS validation/test never in the knowledge base; S3 on the same 191 cases; secondary S4 with KB = MIMIC-IV-ED only on the same 191 cases (117-case stratified sample first, then the other 74). Frozen configuration sha256 77522c1b1d959477... (live config matches: True).

Generated 2026-11-28T17:00:09Z by `python scripts/evaluate.py --all`; seed 42. LLM: openai/gpt-oss-20b, temperature 0.0, reasoning_effort low. All LLM runs complete: True.

## MIMIC

### Split

| Split | Cases | Groups | Low | Medium | High |
|---|---|---|---|---|---|
| train | 114 | 21 | 0 | 50 | 64 |
| development | 62 | 26 | 1 | 27 | 34 |
| test | 31 | 9 | 1 | 13 | 17 |

### Held-out test split -- LLM-free systems

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 Majority class | 31 | 54.8% [38.7%, 74.2%] | 33.3% | 0.236 [0.186, 0.415] | 0.388 | 0.000 | 100.0% | 0.0% [0.0%, 0.0%] | 45.2% | – |
| S1 Retrieval-only (Agent 2 vote) | 31 | 71.0% [54.8%, 87.1%] | 47.4% | 0.469 [0.356, 0.838] | 0.689 | 0.370 | 88.2% | 6.5% [0.0%, 16.1%] | 22.6% | 0.696 |
| S2a Logistic Regression | 31 | 67.7% [48.4%, 83.9%] | 47.2% | 0.459 [0.344, 0.806] | 0.669 | 0.399 | 64.7% | 19.4% [6.5%, 35.5%] | 12.9% | 0.717 |
| S2b Random Forest | 31 | 71.0% [54.8%, 83.9%] | 48.6% | 0.478 [0.364, 0.836] | 0.698 | 0.385 | 76.5% | 12.9% [3.2%, 25.8%] | 16.1% | 0.705 |

### LLM systems (MIMIC held-out test split, frozen configuration, run once)

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S4 [kb=mimic-train] | 31 | 48.4% [32.3%, 64.6%] | 30.6% | 0.295 [0.190, 0.592] | 0.453 | -0.030 | 76.5% | 16.1% [3.2%, 29.0%] | 35.5% | – |
| S4-noNEWS2 [kb=mimic-train] | 31 | 48.4% [32.3%, 64.6%] | 30.6% | 0.295 [0.190, 0.592] | 0.453 | -0.030 | 76.5% | 16.1% [3.2%, 29.0%] | 35.5% | – |
| S3 [kb=none] | 31 | 61.3% [41.9%, 77.4%] | 41.5% | 0.431 [0.309, 0.782] | 0.631 | 0.213 | 70.6% | 19.4% [6.5%, 32.3%] | 19.4% | – |
| S4-promptv1 [kb=mimic-train] | 31 | 22.6% [9.7%, 38.7%] | 14.9% | 0.222 [0.104, 0.468] | 0.338 | 0.089 | 29.4% | 74.2% [58.1%, 90.3%] | 3.2% | – |

### Development set results (prompt development v1 -> v2; NOT held-out)

Development set = old validation + old test splits; knowledge base = old training split.

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S4 development [kb=mimic-dev-train] | 62 | 59.7% [46.8%, 72.6%] | 38.3% | 0.381 [0.302, 0.674] | 0.581 | 0.239 | 85.3% | 12.9% [4.8%, 22.6%] | 27.4% | – |
| S4-noNEWS2 development [kb=mimic-dev-train] | 62 | 59.7% [46.8%, 72.6%] | 38.3% | 0.381 [0.302, 0.674] | 0.581 | 0.239 | 85.3% | 12.9% [4.8%, 22.6%] | 27.4% | – |
| S4-promptv1 development [kb=mimic-dev-train] | 31 | 29.0% [12.9%, 45.2%] | 52.0% | 0.285 [0.166, 0.519] | 0.353 | 0.039 | 17.6% | 64.5% [48.4%, 80.6%] | 6.5% | – |

### 5-fold cross-validation (train + development set; held-out test untouched)

Method: 5-fold StratifiedGroupKFold on subject_id (train + development set, held-out test untouched)

| System | Accuracy mean ± sd | Macro-F1 mean ± sd | Balanced acc. mean ± sd | Under-triage mean ± sd |
|---|---|---|---|---|
| S0 | 0.571 ± 0.135 | 0.338 ± 0.081 | 0.467 ± 0.075 | 0.000 ± 0.000 |
| S1 | 0.623 ± 0.077 | 0.559 ± 0.121 | 0.592 ± 0.133 | 0.161 ± 0.090 |
| S2a | 0.649 ± 0.054 | 0.599 ± 0.103 | 0.616 ± 0.118 | 0.204 ± 0.092 |
| S2b | 0.659 ± 0.057 | 0.594 ± 0.084 | 0.621 ± 0.104 | 0.135 ± 0.098 |

### Tuned hyperparameters (macro-F1 on the development set)

- S1: k=5, weights={'complaint': 1.0, 'diagnosis': 0.3, 'vitals': 0.25, 'medication': 0.0} (val macro-F1 0.440)
- S2a: {'C': 0.1} (val macro-F1 0.477)
- S2b: {'n_estimators': 200, 'max_depth': 10, 'min_samples_leaf': 1} (val macro-F1 0.463)
- Best non-LLM system by development set macro-F1: S2a

### Retrieval quality (production weights, test queries)

| KB | Queries | No-evidence rate | Mean top-1 similarity | P@1 | P@3 | P@5 |
|---|---|---|---|---|---|---|
| mimic-train | 31 | 3.2% | 0.595 | 0.633 | 0.556 | 0.577 |

### McNemar tests (exact)

| Comparison | A right / B wrong | A wrong / B right | p |
|---|---|---|---|
| mimic:S4:kb=mimic-train vs S2a | 5 | 11 | 0.2101 |
| mimic:S4:kb=mimic-train vs S4-noNEWS2 | 0 | 0 | 1.0000 |
| mimic:S4:kb=mimic-train vs mimic:S3:kb=none | 1 | 5 | 0.2188 |
| mimic:S4:kb=mimic-train vs mimic:S4-promptv1:kb=mimic-train | 10 | 2 | 0.0386 |

### Agent performance

| Job | Cases | First-pass valid | Repair rate | Failed | NEWS2 overrides | Weak-evidence flags | Agent 2 ms (median) | Agent 3 ms (median / p95) | Agent 4 ms (median) | Tokens/case |
|---|---|---|---|---|---|---|---|---|---|---|
| DEVELOPMENT mimic-dev:S4:kb=mimic-dev-train | 62 | 100.0% | 0.0% | 0 | 0 | 29.0% | 2.0 | 598 / 973 | 0.09 | 1671 |
| DEVELOPMENT mimic-dev:S4-promptv1:kb=mimic-dev-train | 31 | 100.0% | 0.0% | 0 | 0 | 38.7% | 2.2 | 635 / 5642 | 0.10 | 1452 |
| mimic:S4:kb=mimic-train | 31 | 100.0% | 0.0% | 0 | 0 | 22.6% | 1.6 | 528 / 980 | 0.08 | 1643 |
| mimic:S3:kb=none | 31 | 100.0% | 0.0% | 0 | 0 | 100.0% | 0.0 | 502 / 641 | 0.05 | 1176 |
| mimic:S4-promptv1:kb=mimic-train | 31 | 100.0% | 0.0% | 0 | 1 | 22.6% | 1.5 | 440 / 810 | 0.08 | 1435 |

### Weak-evidence flag (S4)

| Job | Flagged n | Flagged acc. | Flagged under-triage | Not flagged n | Not flagged acc. | Not flagged under-triage |
|---|---|---|---|---|---|---|
| mimic:S4:kb=mimic-train | 7 | 57.1% | 42.9% | 24 | 45.8% | 8.3% |

### Subgroups (LLM case set)

| System | Grouping | Group | n | Accuracy | Macro-F1 | Under-triage |
|---|---|---|---|---|---|---|
| S2b | sex | F | 11 | 81.8% | 0.571 | 9.1% |
| S2b | sex | M | 20 | 65.0% | 0.649 | 15.0% |
| S4 (mimic-train) | sex | F | 11 | 45.5% | 0.324 | 27.3% |
| S4 (mimic-train) | sex | M | 20 | 50.0% | 0.424 | 10.0% |

### LOW_EVIDENCE_THRESHOLD selection

- Rule: largest accuracy drop (unflagged - flagged) with 10-40% of cases flagged
- Signal: top-1 similarity, production retrieval weights, k=5
- Chosen (development OOF, n=176): 0.5 -> {'threshold': np.float64(0.5), 'n_flagged': 59, 'flag_rate': 0.335, 'acc_flagged': 0.61, 'acc_unflagged': 0.624, 'accuracy_drop': 0.014}
- Validation-only choice (n=62): {'threshold': np.float64(0.425), 'n_flagged': 8, 'flag_rate': 0.129, 'acc_flagged': 0.375, 'acc_unflagged': 0.685, 'accuracy_drop': 0.31}
- Value in config: 0.5

### Warnings

- S0: classes with <5 examples: ['Low']; classes absent from ground truth: [] -- per-class metrics for these are unreliable
- S1: classes with <5 examples: ['Low']; classes absent from ground truth: [] -- per-class metrics for these are unreliable
- S2a: classes with <5 examples: ['Low']; classes absent from ground truth: [] -- per-class metrics for these are unreliable

## KTAS

### Split

| Split | Cases | Groups | Low | Medium | High |
|---|---|---|---|---|---|
| train | 886 | 886 | 373 | 341 | 172 |
| validation | 190 | 190 | 80 | 73 | 37 |
| test | 191 | 191 | 81 | 73 | 37 |

### Test split -- LLM-free systems

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 Majority class | 191 | 42.4% [35.6%, 49.7%] | 33.3% | 0.199 [0.175, 0.221] | 0.253 | 0.000 | 0.0% | 57.6% [50.3%, 64.4%] | 0.0% | – |
| S1 Retrieval-only (Agent 2 vote) | 191 | 65.4% [58.1%, 72.3%] | 64.1% | 0.648 [0.575, 0.717] | 0.652 | 0.523 | 59.5% | 20.9% [15.2%, 26.7%] | 13.6% | 0.792 |
| S2a Logistic Regression | 191 | 69.1% [62.3%, 75.9%] | 70.5% | 0.700 [0.631, 0.763] | 0.689 | 0.593 | 78.4% | 15.7% [11.0%, 20.9%] | 15.2% | 0.848 |
| S2b Random Forest | 191 | 70.7% [63.9%, 77.0%] | 70.1% | 0.704 [0.634, 0.765] | 0.708 | 0.596 | 67.6% | 14.1% [9.4%, 19.4%] | 15.2% | 0.855 |
| H Triage nurse (KTAS_RN) | 191 | 88.0% [83.2%, 92.7%] | 88.4% | 0.880 [0.831, 0.927] | 0.879 | 0.851 | 91.9% | 6.3% [3.1%, 9.9%] | 5.8% | – |
| S1-mk Retrieval-only vote, multi-source KB (MIMIC-IV-ED + KTAS train) | 191 | 64.4% [57.6%, 71.2%] | 62.7% | 0.635 [0.560, 0.702] | 0.642 | 0.508 | 56.8% | 21.5% [15.7%, 27.2%] | 14.1% | 0.783 |

Triage nurse on all KTAS records:

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| H Triage nurse (KTAS_RN), all records | 1267 | 88.6% [86.9%, 90.4%] | 87.9% | 0.884 [0.865, 0.904] | 0.885 | 0.846 | 86.2% | 8.3% [6.8%, 9.8%] | 3.2% | – |

### LLM systems (KTAS test split, MAIN evaluation, frozen configuration; KB mimic+ktas-train = all MIMIC-IV-ED + KTAS train)

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S4 [kb=mimic+ktas-train] | 191 | 60.2% [53.4%, 67.0%] | 63.5% | 0.603 [0.534, 0.671] | 0.597 | 0.474 | 81.1% | 15.2% [9.9%, 20.4%] | 24.6% | – |
| S4-noNEWS2 [kb=mimic+ktas-train] | 191 | 61.8% [55.5%, 69.1%] | 64.8% | 0.620 [0.554, 0.688] | 0.612 | 0.500 | 81.1% | 15.2% [9.9%, 20.4%] | 23.0% | – |
| S3 [kb=none] | 191 | 60.7% [53.4%, 67.5%] | 63.6% | 0.613 [0.542, 0.679] | 0.604 | 0.463 | 78.4% | 15.2% [9.9%, 20.4%] | 24.1% | – |
| S4 [kb=mimic-all] | 191 | 61.8% [54.5%, 68.6%] | 65.6% | 0.609 [0.535, 0.678] | 0.611 | 0.506 | 86.5% | 12.0% [7.9%, 17.3%] | 26.2% | – |
| S4-noNEWS2 [kb=mimic-all] | 191 | 61.8% [54.5%, 68.6%] | 65.1% | 0.608 [0.531, 0.675] | 0.611 | 0.513 | 83.8% | 12.6% [8.4%, 17.8%] | 25.7% | – |

### Same 117-case KTAS sample (secondary job, KB = MIMIC-IV-ED only) -- LLM-free systems and nurse

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 Majority class | 117 | 34.2% [25.6%, 42.7%] | 33.3% | 0.170 [0.136, 0.200] | 0.174 | 0.000 | 0.0% | 65.8% [57.3%, 74.4%] | 0.0% | – |
| S1 Retrieval-only (Agent 2 vote) | 117 | 67.5% [59.0%, 76.1%] | 67.3% | 0.674 [0.583, 0.750] | 0.674 | 0.569 | 59.5% | 21.4% [13.7%, 29.1%] | 11.1% | – |
| S2a Logistic Regression | 117 | 72.6% [65.0%, 80.3%] | 72.8% | 0.727 [0.649, 0.802] | 0.725 | 0.673 | 78.4% | 14.5% [7.7%, 20.5%] | 12.8% | – |
| S2b Random Forest | 117 | 68.4% [59.8%, 76.1%] | 68.4% | 0.688 [0.604, 0.767] | 0.687 | 0.604 | 67.6% | 17.9% [11.1%, 24.8%] | 13.7% | – |
| H Triage nurse (KTAS_RN) | 117 | 87.2% [80.3%, 93.2%] | 87.3% | 0.874 [0.809, 0.929] | 0.872 | 0.854 | 91.9% | 6.8% [2.6%, 12.0%] | 6.0% | – |

### 5-fold cross-validation (train + validation split; held-out test untouched)

Method: 5-fold StratifiedKFold (train+validation, test untouched)

| System | Accuracy mean ± sd | Macro-F1 mean ± sd | Balanced acc. mean ± sd | Under-triage mean ± sd |
|---|---|---|---|---|
| S0 | 0.421 ± 0.002 | 0.198 ± 0.001 | 0.333 ± 0.000 | 0.579 ± 0.002 |
| S1 | 0.652 ± 0.031 | 0.644 ± 0.032 | 0.648 ± 0.035 | 0.177 ± 0.023 |
| S2a | 0.685 ± 0.055 | 0.677 ± 0.057 | 0.686 ± 0.064 | 0.141 ± 0.040 |
| S2b | 0.713 ± 0.018 | 0.705 ± 0.021 | 0.711 ± 0.026 | 0.126 ± 0.019 |

### Tuned hyperparameters (macro-F1 on the validation split)

- S1: k=3, weights={'complaint': 1.0, 'diagnosis': 0.3, 'vitals': 0.25, 'medication': 0.3} (val macro-F1 0.689)
- S2a: {'C': 3.0} (val macro-F1 0.698)
- S2b: {'n_estimators': 200, 'max_depth': None, 'min_samples_leaf': 3} (val macro-F1 0.711)
- Best non-LLM system by validation split macro-F1: S2b

### Retrieval quality (production weights, test queries)

| KB | Queries | No-evidence rate | Mean top-1 similarity | P@1 | P@3 | P@5 |
|---|---|---|---|---|---|---|
| mimic-all+ktas-train | 191 | 2.6% | 0.710 | 0.548 | 0.593 | 0.583 |
| ktas-train | 191 | 2.6% | 0.700 | 0.591 | 0.618 | 0.611 |
| mimic-all | 191 | 9.4% | 0.565 | 0.318 | 0.319 | 0.321 |

### McNemar tests (exact)

| Comparison | A right / B wrong | A wrong / B right | p |
|---|---|---|---|
| ktas:S4:kb=mimic+ktas-train vs S2b | 21 | 41 | 0.0151 |
| ktas:S4:kb=mimic+ktas-train vs S4-noNEWS2 | 0 | 3 | 0.2500 |
| ktas:S4:kb=mimic+ktas-train vs H | 15 | 68 | 0.0000 |
| ktas:S4:kb=mimic+ktas-train vs ktas:S3:kb=none | 24 | 25 | 1.0000 |
| ktas:S4:kb=mimic+ktas-train vs ktas:S4:kb=mimic-all | 15 | 18 | 0.7283 |
| ktas:S4:kb=mimic-all vs S2b | 26 | 43 | 0.0533 |
| ktas:S4:kb=mimic-all vs S4-noNEWS2 | 1 | 1 | 1.0000 |
| ktas:S4:kb=mimic-all vs H | 13 | 63 | 0.0000 |
| ktas:S4:kb=mimic-all vs ktas:S3:kb=none | 28 | 26 | 0.8919 |

### Agent performance

| Job | Cases | First-pass valid | Repair rate | Failed | NEWS2 overrides | Weak-evidence flags | Agent 2 ms (median) | Agent 3 ms (median / p95) | Agent 4 ms (median) | Tokens/case |
|---|---|---|---|---|---|---|---|---|---|---|
| ktas:S4:kb=mimic+ktas-train | 191 | 100.0% | 0.0% | 0 | 3 | 9.4% | 13.6 | 565 / 873 | 0.09 | 1524 |
| ktas:S3:kb=none | 191 | 100.0% | 0.0% | 0 | 3 | 100.0% | 0.0 | 406 / 783 | 0.04 | 1179 |
| ktas:S4:kb=mimic-all | 191 | 100.0% | 0.0% | 0 | 3 | 32.5% | 2.9 | 565 / 989 | 0.10 | 1619 |

### Weak-evidence flag (S4)

| Job | Flagged n | Flagged acc. | Flagged under-triage | Not flagged n | Not flagged acc. | Not flagged under-triage |
|---|---|---|---|---|---|---|
| ktas:S4:kb=mimic+ktas-train | 18 | 38.9% | 16.7% | 173 | 62.4% | 15.0% |
| ktas:S4:kb=mimic-all | 62 | 69.4% | 11.3% | 129 | 58.1% | 12.4% |

### Subgroups (LLM case set)

| System | Grouping | Group | n | Accuracy | Macro-F1 | Under-triage |
|---|---|---|---|---|---|---|
| S2b | sex | F | 93 | 72.0% | 0.709 | 12.9% |
| S2b | sex | M | 98 | 69.4% | 0.690 | 15.3% |
| S2b | age_band | 40-64 | 67 | 65.7% | 0.664 | 11.9% |
| S2b | age_band | 65+ | 72 | 76.4% | 0.766 | 15.3% |
| S2b | age_band | <40 | 52 | 69.2% | 0.581 | 15.4% |
| H | sex | F | 93 | 89.2% | 0.895 | 5.4% |
| H | sex | M | 98 | 86.7% | 0.862 | 7.1% |
| H | age_band | 40-64 | 67 | 86.6% | 0.854 | 6.0% |
| H | age_band | 65+ | 72 | 90.3% | 0.905 | 6.9% |
| H | age_band | <40 | 52 | 86.5% | 0.853 | 5.8% |
| S4 (mimic-all+ktas-train) | sex | F | 93 | 63.4% | 0.635 | 18.3% |
| S4 (mimic-all+ktas-train) | sex | M | 98 | 57.1% | 0.569 | 12.2% |
| S4 (mimic-all+ktas-train) | age_band | 40-64 | 67 | 59.7% | 0.604 | 17.9% |
| S4 (mimic-all+ktas-train) | age_band | 65+ | 72 | 56.9% | 0.562 | 16.7% |
| S4 (mimic-all+ktas-train) | age_band | <40 | 52 | 65.4% | 0.544 | 9.6% |
| S4 (mimic-all) | sex | F | 93 | 58.1% | 0.579 | 19.4% |
| S4 (mimic-all) | sex | M | 98 | 65.3% | 0.638 | 5.1% |
| S4 (mimic-all) | age_band | 40-64 | 67 | 59.7% | 0.590 | 13.4% |
| S4 (mimic-all) | age_band | 65+ | 72 | 58.3% | 0.578 | 12.5% |
| S4 (mimic-all) | age_band | <40 | 52 | 69.2% | 0.589 | 9.6% |

## Figures

- `evaluation/results/figures/confusion_matrices_mimic.png`
- `evaluation/results/figures/model_comparison_f1_mimic.png`
- `evaluation/results/figures/under_triage_mimic.png`
- `evaluation/results/figures/cv_boxplot_mimic.png`
- `evaluation/results/figures/per_class_f1_mimic.png`
- `evaluation/results/figures/subgroups_mimic.png`
- `evaluation/results/figures/confusion_matrices_ktas.png`
- `evaluation/results/figures/model_comparison_f1_ktas.png`
- `evaluation/results/figures/under_triage_ktas.png`
- `evaluation/results/figures/cv_boxplot_ktas.png`
- `evaluation/results/figures/per_class_f1_ktas.png`
- `evaluation/results/figures/subgroups_ktas.png`
- `evaluation/results/figures/nurse_vs_system_ktas.png`
- `evaluation/results/figures/latency_per_agent.png`
- `evaluation/results/figures/low_evidence_accuracy.png`
