# Evaluation summary (tables only)

Generated 2026-11-21T01:21:42Z by `python scripts/evaluate.py --all`; seed 42. LLM: openai/gpt-oss-20b, temperature 0.0, reasoning_effort low. All LLM runs complete: False.

## MIMIC

### Split

| Split | Cases | Groups | Low | Medium | High |
|---|---|---|---|---|---|
| train | 145 | 30 | 1 | 63 | 81 |
| validation | 31 | 15 | 0 | 14 | 17 |
| test | 31 | 11 | 1 | 13 | 17 |

### Test split -- LLM-free systems

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 Majority class | 31 | 54.8% [38.7%, 74.2%] | 33.3% | 0.236 [0.186, 0.415] | 0.388 | 0.000 | 100.0% | 0.0% [0.0%, 0.0%] | 45.2% | – |
| S1 Retrieval-only (Agent 2 vote) | 31 | 58.1% [38.7%, 74.2%] | 41.9% | 0.389 [0.274, 0.708] | 0.556 | 0.178 | 41.2% | 32.3% [16.1%, 48.5%] | 9.7% | 0.783 |
| S2a Logistic Regression | 31 | 67.7% [51.6%, 83.9%] | 47.2% | 0.459 [0.343, 0.827] | 0.669 | 0.399 | 64.7% | 19.4% [6.5%, 35.5%] | 12.9% | 0.659 |
| S2b Random Forest | 31 | 71.0% [54.8%, 87.1%] | 48.6% | 0.477 [0.367, 0.838] | 0.699 | 0.450 | 76.5% | 12.9% [3.2%, 25.8%] | 16.1% | 0.693 |

### LLM systems (test split)

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S4-promptv1 [kb=mimic-train] | 31 | 29.0% [12.9%, 45.2%] | 52.0% | 0.285 [0.166, 0.519] | 0.353 | 0.039 | 17.6% | 64.5% [48.4%, 80.6%] | 6.5% | – |
| S4 [kb=mimic-train] | 31 | 61.3% [45.2%, 77.4%] | 40.3% | 0.391 [0.280, 0.718] | 0.584 | 0.244 | 82.4% | 9.7% [0.0%, 22.6%] | 29.0% | – |
| S4-noNEWS2 [kb=mimic-train] | 31 | 61.3% [45.2%, 77.4%] | 40.3% | 0.391 [0.280, 0.718] | 0.584 | 0.244 | 82.4% | 9.7% [0.0%, 22.6%] | 29.0% | – |
| S3 [kb=none] (INCOMPLETE 10/31) | 10 | 60.0% [30.0%, 90.0%] | 60.0% | 0.750 [0.462, 0.947] | 0.750 | 0.000 | 60.0% | 40.0% [10.0%, 70.0%] | 0.0% | – |

### LLM systems on the validation split (prompt check before the test run)

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S4 validation [kb=mimic-train] | 31 | 58.1% [41.9%, 74.2%] | 54.8% | 0.551 [0.370, 0.716] | 0.571 | 0.241 | 88.2% | 16.1% [6.4%, 29.0%] | 25.8% | – |

### 5-fold cross-validation (development = train + validation)

Method: 5-fold StratifiedGroupKFold on subject_id (train+validation, test untouched)

| System | Accuracy mean ± sd | Macro-F1 mean ± sd | Balanced acc. mean ± sd | Under-triage mean ± sd |
|---|---|---|---|---|
| S0 | 0.577 ± 0.117 | 0.343 ± 0.085 | 0.467 ± 0.075 | 0.000 ± 0.000 |
| S1 | 0.626 ± 0.049 | 0.575 ± 0.108 | 0.596 ± 0.113 | 0.209 ± 0.096 |
| S2a | 0.635 ± 0.086 | 0.569 ± 0.052 | 0.581 ± 0.054 | 0.247 ± 0.108 |
| S2b | 0.661 ± 0.057 | 0.608 ± 0.118 | 0.630 ± 0.119 | 0.194 ± 0.096 |

### Tuned hyperparameters (validation macro-F1)

- S1: k=3, weights={'complaint': 1.0, 'diagnosis': 0.7, 'vitals': 0.25, 'medication': 0.0} (val macro-F1 0.674)
- S2a: {'C': 0.1} (val macro-F1 0.688)
- S2b: {'n_estimators': 200, 'max_depth': 5, 'min_samples_leaf': 3} (val macro-F1 0.739)
- Best non-LLM system by validation macro-F1: S2b

### Retrieval quality (production weights, test queries)

| KB | Queries | No-evidence rate | Mean top-1 similarity | P@1 | P@3 | P@5 |
|---|---|---|---|---|---|---|
| mimic-train | 31 | 6.5% | 0.587 | 0.655 | 0.540 | 0.579 |

### McNemar tests (exact)

| Comparison | A right / B wrong | A wrong / B right | p |
|---|---|---|---|
| mimic:S4:kb=mimic-train vs S2b | 7 | 10 | 0.6291 |
| mimic:S4:kb=mimic-train vs S4-noNEWS2 | 0 | 0 | 1.0000 |

### Agent performance

| Job | Cases | First-pass valid | Repair rate | Failed | NEWS2 overrides | Weak-evidence flags | Agent 2 ms (median) | Agent 3 ms (median / p95) | Agent 4 ms (median) | Tokens/case |
|---|---|---|---|---|---|---|---|---|---|---|
| mimic:S4-promptv1:kb=mimic-train | 31 | 100.0% | 0.0% | 0 | 0 | 38.7% | 2.5 | 635 / 5642 | -634.80 | 1452 |
| mimic:S4:kb=mimic-train | 31 | 100.0% | 0.0% | 0 | 0 | 38.7% | 2.5 | 573 / 985 | -572.40 | 1680 |
| mimic:S3:kb=none | 10 | 100.0% | 0.0% | 0 | 0 | 100.0% | 0.0 | 417 / 598 | -416.75 | 1176 |

### Weak-evidence flag (S4)

| Job | Flagged n | Flagged acc. | Flagged under-triage | Not flagged n | Not flagged acc. | Not flagged under-triage |
|---|---|---|---|---|---|---|
| mimic:S4:kb=mimic-train | 12 | 50.0% | 16.7% | 19 | 68.4% | 5.3% |

### Subgroups (LLM case set)

| System | Grouping | Group | n | Accuracy | Macro-F1 | Under-triage |
|---|---|---|---|---|---|---|
| S2b | sex | F | 20 | 75.0% | 0.512 | 10.0% |
| S2b | sex | M | 11 | 63.6% | 0.607 | 18.2% |
| S4 (mimic-train) | sex | F | 20 | 60.0% | 0.399 | 10.0% |
| S4 (mimic-train) | sex | M | 11 | 63.6% | 0.542 | 9.1% |

### LOW_EVIDENCE_THRESHOLD selection

- Rule: largest accuracy drop (unflagged - flagged) with 10-40% of cases flagged
- Signal: top-1 similarity, production retrieval weights, k=5
- Chosen (development OOF, n=176): 0.5 -> {'threshold': np.float64(0.5), 'n_flagged': 54, 'flag_rate': 0.307, 'acc_flagged': 0.574, 'acc_unflagged': 0.615, 'accuracy_drop': 0.041}
- Validation-only choice (n=31): {'threshold': np.float64(0.575), 'n_flagged': 11, 'flag_rate': 0.355, 'acc_flagged': 0.636, 'acc_unflagged': 0.6, 'accuracy_drop': -0.036}
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

### LLM systems (test split sample)

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|

### Same 117-case KTAS subset -- LLM-free systems and nurse

| System | n | Accuracy [95% CI] | Balanced acc. | Macro-F1 [95% CI] | Weighted F1 | Kappa (linear) | High recall | Under-triage [95% CI] | Over-triage | ROC-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 Majority class | 117 | 34.2% [25.6%, 42.7%] | 33.3% | 0.170 [0.136, 0.200] | 0.174 | 0.000 | 0.0% | 65.8% [57.3%, 74.4%] | 0.0% | – |
| S1 Retrieval-only (Agent 2 vote) | 117 | 67.5% [59.0%, 76.1%] | 67.3% | 0.674 [0.583, 0.750] | 0.674 | 0.569 | 59.5% | 21.4% [13.7%, 29.1%] | 11.1% | – |
| S2a Logistic Regression | 117 | 72.6% [65.0%, 80.3%] | 72.8% | 0.727 [0.649, 0.802] | 0.725 | 0.673 | 78.4% | 14.5% [7.7%, 20.5%] | 12.8% | – |
| S2b Random Forest | 117 | 68.4% [59.8%, 76.1%] | 68.4% | 0.688 [0.604, 0.767] | 0.687 | 0.604 | 67.6% | 17.9% [11.1%, 24.8%] | 13.7% | – |
| H Triage nurse (KTAS_RN) | 117 | 87.2% [80.3%, 93.2%] | 87.3% | 0.874 [0.809, 0.929] | 0.872 | 0.854 | 91.9% | 6.8% [2.6%, 12.0%] | 6.0% | – |

### 5-fold cross-validation (development = train + validation)

Method: 5-fold StratifiedKFold (train+validation, test untouched)

| System | Accuracy mean ± sd | Macro-F1 mean ± sd | Balanced acc. mean ± sd | Under-triage mean ± sd |
|---|---|---|---|---|
| S0 | 0.421 ± 0.002 | 0.198 ± 0.001 | 0.333 ± 0.000 | 0.579 ± 0.002 |
| S1 | 0.652 ± 0.031 | 0.644 ± 0.032 | 0.648 ± 0.035 | 0.177 ± 0.023 |
| S2a | 0.685 ± 0.055 | 0.677 ± 0.057 | 0.686 ± 0.064 | 0.141 ± 0.040 |
| S2b | 0.713 ± 0.018 | 0.705 ± 0.021 | 0.711 ± 0.026 | 0.126 ± 0.019 |

### Tuned hyperparameters (validation macro-F1)

- S1: k=3, weights={'complaint': 1.0, 'diagnosis': 0.3, 'vitals': 0.25, 'medication': 0.3} (val macro-F1 0.689)
- S2a: {'C': 3.0} (val macro-F1 0.698)
- S2b: {'n_estimators': 200, 'max_depth': None, 'min_samples_leaf': 3} (val macro-F1 0.711)
- Best non-LLM system by validation macro-F1: S2b

### Retrieval quality (production weights, test queries)

| KB | Queries | No-evidence rate | Mean top-1 similarity | P@1 | P@3 | P@5 |
|---|---|---|---|---|---|---|
| ktas-train | 191 | 2.6% | 0.700 | 0.591 | 0.618 | 0.611 |
| mimic-all | 191 | 9.4% | 0.565 | 0.318 | 0.319 | 0.321 |

### Subgroups (LLM case set)

| System | Grouping | Group | n | Accuracy | Macro-F1 | Under-triage |
|---|---|---|---|---|---|---|
| S2b | sex | F | 55 | 63.6% | 0.643 | 20.0% |
| S2b | sex | M | 62 | 72.6% | 0.718 | 16.1% |
| S2b | age_band | 40-64 | 39 | 61.5% | 0.622 | 12.8% |
| S2b | age_band | 65+ | 50 | 76.0% | 0.775 | 18.0% |
| S2b | age_band | <40 | 28 | 64.3% | 0.610 | 25.0% |
| H | sex | F | 55 | 89.1% | 0.896 | 5.5% |
| H | sex | M | 62 | 85.5% | 0.843 | 8.1% |
| H | age_band | 40-64 | 39 | 87.2% | 0.855 | 5.1% |
| H | age_band | 65+ | 50 | 90.0% | 0.896 | 6.0% |
| H | age_band | <40 | 28 | 82.1% | 0.867 | 10.7% |

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
- `evaluation/results/figures/latency_per_agent.png`
- `evaluation/results/figures/low_evidence_accuracy.png`
