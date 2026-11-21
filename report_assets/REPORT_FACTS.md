# REPORT FACTS (bullet facts and numbers only -- not report text)

- Source: `evaluation/results/metrics.json` generated 2026-11-21T01:21:42Z; seed 42
- All LLM runs complete: False

## Datasets
- MIMIC-IV-ED Demo v2.2: 64 patients, 222 ED stays, 207 stays with ESI acuity (56 patients); 15 unlabelled excluded
- MIMIC 3-class labels (ESI 1-2 High, 3 Medium, 4-5 Low): High 115, Medium 90, Low 2
- MIMIC knowledge base tables: edstays, triage, diagnosis (545 rows), vitalsign (1,038), medrecon (2,764), pyxis (1,082)
- MIMIC temperature unit: deg F; 1 triage temperature recorded in deg C (36.5) converted; 1 DBP of 879 set missing
- KTAS: Moon et al. (2019) PLoS ONE 14(9) e0216972; 1,267 adult ED visits; 2 Korean EDs (local 688, regional 579); Oct 2016 - Sep 2017; CC BY 4.0
- KTAS ground truth = KTAS_expert: High 246, Medium 487, Low 534; nurse baseline KTAS_RN: High 232, Medium 447, Low 588
- KTAS inputs excluded (leak answer / post-triage): KTAS_RN, KTAS_expert, Error_group, mistriage, Diagnosis in ED, Disposition, Length of stay_min, KTAS duration_min
- KTAS cleaning: 19 distinct Korean complaints (21 rows) translated; 'F/C, C/S' expanded (2 rows); Greek alpha folded (1 row); 0 rows dropped
- KTAS vitals: Korean '측불' (unmeasurable) -> missing (SBP 25, DBP 29, HR 20, RR 22, BT 18, SpO2 9); SpO2 not recorded at the local ED (688 rows); BT deg C -> deg F

## Splits
- MIMIC train: 145 cases, 30 patients (70%); Low 1, Medium 63, High 81
- MIMIC validation: 31 cases, 15 patients (15%); Low 0, Medium 14, High 17
- MIMIC test: 31 cases, 11 patients (15%); Low 1, Medium 13, High 17
- KTAS train: 886 cases, 886 rows (70%); Low 373, Medium 341, High 172
- KTAS validation: 190 cases, 190 rows (15%); Low 80, Medium 73, High 37
- KTAS test: 191 cases, 191 rows (15%); Low 81, Medium 73, High 37
- MIMIC split method: patient-grouped stratified 70/15/15 (no patient in two splits)
- KTAS split method: stratified 70/15/15 on the 3-class expert label
- KTAS LLM sample: 117 test cases (40 Low, 40 Medium, all 37 High test cases)
- MIMIC evaluation knowledge base: training stays only (leakage control; unit test proves no test stay is retrieved)
- KTAS knowledge bases: KB=MIMIC (all 222 stays, deployed system) and KB=KTAS-train (886 rows)

## Hyperparameters chosen on validation
- MIMIC S1: k=3, weights {'complaint': 1.0, 'diagnosis': 0.7, 'vitals': 0.25, 'medication': 0.0}
- MIMIC S2a LR: {'C': 0.1} (class_weight balanced)
- MIMIC S2b RF: {'n_estimators': 200, 'max_depth': 5, 'min_samples_leaf': 3} (class_weight balanced)
- MIMIC best non-LLM system by validation macro-F1: S2b
- KTAS S1: k=3, weights {'complaint': 1.0, 'diagnosis': 0.3, 'vitals': 0.25, 'medication': 0.3}
- KTAS S2a LR: {'C': 3.0} (class_weight balanced)
- KTAS S2b RF: {'n_estimators': 200, 'max_depth': None, 'min_samples_leaf': 3} (class_weight balanced)
- KTAS best non-LLM system by validation macro-F1: S2b
- LOW_EVIDENCE_THRESHOLD = 0.5 (top-1 similarity); rule: largest accuracy drop (unflagged - flagged) with 10-40% of cases flagged; chosen on MIMIC development OOF (n=176): flag rate 0.307, accuracy flagged 0.574 vs unflagged 0.615
- LLM: openai/gpt-oss-20b, temperature 0.0, max_tokens 1024, reasoning_effort low, max repairs 2, prompt v2

## Results -- MIMIC test
- S0 (Majority class): n=31; accuracy 54.8% (95% CI 38.7%-74.2%); balanced accuracy 33.3%; macro-F1 0.236 (95% CI 0.186-0.415); weighted F1 0.388; linear kappa 0.000; High recall 100.0%; under-triage 0.0% (95% CI 0.0%-0.0%); over-triage 45.2%
- S1 (Retrieval-only (Agent 2 vote)): n=31; accuracy 58.1% (95% CI 38.7%-74.2%); balanced accuracy 41.9%; macro-F1 0.389 (95% CI 0.274-0.708); weighted F1 0.556; linear kappa 0.178; High recall 41.2%; under-triage 32.3% (95% CI 16.1%-48.5%); over-triage 9.7%; ROC-AUC 0.783
- S2a (Logistic Regression): n=31; accuracy 67.7% (95% CI 51.6%-83.9%); balanced accuracy 47.2%; macro-F1 0.459 (95% CI 0.343-0.827); weighted F1 0.669; linear kappa 0.399; High recall 64.7%; under-triage 19.4% (95% CI 6.5%-35.5%); over-triage 12.9%; ROC-AUC 0.659
- S2b (Random Forest): n=31; accuracy 71.0% (95% CI 54.8%-87.1%); balanced accuracy 48.6%; macro-F1 0.477 (95% CI 0.367-0.838); weighted F1 0.699; linear kappa 0.450; High recall 76.5%; under-triage 12.9% (95% CI 3.2%-25.8%); over-triage 16.1%; ROC-AUC 0.693
- S4-promptv1 KB=mimic-train: n=31; accuracy 29.0% (95% CI 12.9%-45.2%); balanced accuracy 52.0%; macro-F1 0.285 (95% CI 0.166-0.519); weighted F1 0.353; linear kappa 0.039; High recall 17.6%; under-triage 64.5% (95% CI 48.4%-80.6%); over-triage 6.5%
- S4 KB=mimic-train: n=31; accuracy 61.3% (95% CI 45.2%-77.4%); balanced accuracy 40.3%; macro-F1 0.391 (95% CI 0.280-0.718); weighted F1 0.584; linear kappa 0.244; High recall 82.4%; under-triage 9.7% (95% CI 0.0%-22.6%); over-triage 29.0%
- S4-noNEWS2 KB=mimic-train: n=31; accuracy 61.3% (95% CI 45.2%-77.4%); balanced accuracy 40.3%; macro-F1 0.391 (95% CI 0.280-0.718); weighted F1 0.584; linear kappa 0.244; High recall 82.4%; under-triage 9.7% (95% CI 0.0%-22.6%); over-triage 29.0%
- S3 KB=none [INCOMPLETE 10/31]: n=10; accuracy 60.0% (95% CI 30.0%-90.0%); balanced accuracy 60.0%; macro-F1 0.750 (95% CI 0.462-0.947); weighted F1 0.750; linear kappa 0.000; High recall 60.0%; under-triage 40.0% (95% CI 10.0%-70.0%); over-triage 0.0%
- S4 on VALIDATION (mimic-val:S4:kb=mimic-train): n=31; accuracy 58.1% (95% CI 41.9%-74.2%); balanced accuracy 54.8%; macro-F1 0.551 (95% CI 0.370-0.716); weighted F1 0.571; linear kappa 0.241; High recall 88.2%; under-triage 16.1% (95% CI 6.4%-29.0%); over-triage 25.8%
- 5-fold CV (5-fold StratifiedGroupKFold on subject_id (train+validation, test untouched)): S0 macro-F1 0.343 ± 0.085, accuracy 0.577 ± 0.117; S1 macro-F1 0.575 ± 0.108, accuracy 0.626 ± 0.049; S2a macro-F1 0.569 ± 0.052, accuracy 0.635 ± 0.086; S2b macro-F1 0.608 ± 0.118, accuracy 0.661 ± 0.057
- Retrieval quality KB=mimic-train: P@1 0.655, P@3 0.540, P@5 0.579, mean top-1 similarity 0.587, no-evidence rate 6.5%
- McNemar mimic:S4:kb=mimic-train vs S2b: 7 vs 10 discordant, exact p = 0.6291
- McNemar mimic:S4:kb=mimic-train vs S4-noNEWS2: 0 vs 0 discordant, exact p = 1.0000
- Agent performance mimic:S4-promptv1:kb=mimic-train: first-pass guardrail validity 100.0%, repair rate 0.0%, failed 0, NEWS2 overrides 0, weak-evidence flags 38.7%, median latency Agent 2 2.5 ms / Agent 3 635 ms (p95 5642) / Agent 4 -634.80 ms, tokens per case 1452
- Agent performance mimic:S4:kb=mimic-train: first-pass guardrail validity 100.0%, repair rate 0.0%, failed 0, NEWS2 overrides 0, weak-evidence flags 38.7%, median latency Agent 2 2.5 ms / Agent 3 573 ms (p95 985) / Agent 4 -572.40 ms, tokens per case 1680
- Agent performance mimic:S3:kb=none: first-pass guardrail validity 100.0%, repair rate 0.0%, failed 0, NEWS2 overrides 0, weak-evidence flags 100.0%, median latency Agent 2 0.0 ms / Agent 3 417 ms (p95 598) / Agent 4 -416.75 ms, tokens per case 1176
- Weak-evidence flag mimic:S4:kb=mimic-train: flagged n=12 accuracy 50.0% under-triage 16.7%; not flagged n=19 accuracy 68.4% under-triage 5.3%
- Subgroup S2b by sex: F n=20 acc 75.0% under 10.0%; M n=11 acc 63.6% under 18.2%
- Subgroup S4 (mimic-train) by sex: F n=20 acc 60.0% under 10.0%; M n=11 acc 63.6% under 9.1%

## Results -- KTAS test
- S0 (Majority class): n=191; accuracy 42.4% (95% CI 35.6%-49.7%); balanced accuracy 33.3%; macro-F1 0.199 (95% CI 0.175-0.221); weighted F1 0.253; linear kappa 0.000; High recall 0.0%; under-triage 57.6% (95% CI 50.3%-64.4%); over-triage 0.0%
- S1 (Retrieval-only (Agent 2 vote)): n=191; accuracy 65.4% (95% CI 58.1%-72.3%); balanced accuracy 64.1%; macro-F1 0.648 (95% CI 0.575-0.717); weighted F1 0.652; linear kappa 0.523; High recall 59.5%; under-triage 20.9% (95% CI 15.2%-26.7%); over-triage 13.6%; ROC-AUC 0.792
- S2a (Logistic Regression): n=191; accuracy 69.1% (95% CI 62.3%-75.9%); balanced accuracy 70.5%; macro-F1 0.700 (95% CI 0.631-0.763); weighted F1 0.689; linear kappa 0.593; High recall 78.4%; under-triage 15.7% (95% CI 11.0%-20.9%); over-triage 15.2%; ROC-AUC 0.848
- S2b (Random Forest): n=191; accuracy 70.7% (95% CI 63.9%-77.0%); balanced accuracy 70.1%; macro-F1 0.704 (95% CI 0.634-0.765); weighted F1 0.708; linear kappa 0.596; High recall 67.6%; under-triage 14.1% (95% CI 9.4%-19.4%); over-triage 15.2%; ROC-AUC 0.855
- H (Triage nurse (KTAS_RN)): n=191; accuracy 88.0% (95% CI 83.2%-92.7%); balanced accuracy 88.4%; macro-F1 0.880 (95% CI 0.831-0.927); weighted F1 0.879; linear kappa 0.851; High recall 91.9%; under-triage 6.3% (95% CI 3.1%-9.9%); over-triage 5.8%
- Same 117-case KTAS LLM sample:
  - S0 (Majority class): n=117; accuracy 34.2% (95% CI 25.6%-42.7%); balanced accuracy 33.3%; macro-F1 0.170 (95% CI 0.136-0.200); weighted F1 0.174; linear kappa 0.000; High recall 0.0%; under-triage 65.8% (95% CI 57.3%-74.4%); over-triage 0.0%
  - S1 (Retrieval-only (Agent 2 vote)): n=117; accuracy 67.5% (95% CI 59.0%-76.1%); balanced accuracy 67.3%; macro-F1 0.674 (95% CI 0.583-0.750); weighted F1 0.674; linear kappa 0.569; High recall 59.5%; under-triage 21.4% (95% CI 13.7%-29.1%); over-triage 11.1%
  - S2a (Logistic Regression): n=117; accuracy 72.6% (95% CI 65.0%-80.3%); balanced accuracy 72.8%; macro-F1 0.727 (95% CI 0.649-0.802); weighted F1 0.725; linear kappa 0.673; High recall 78.4%; under-triage 14.5% (95% CI 7.7%-20.5%); over-triage 12.8%
  - S2b (Random Forest): n=117; accuracy 68.4% (95% CI 59.8%-76.1%); balanced accuracy 68.4%; macro-F1 0.688 (95% CI 0.604-0.767); weighted F1 0.687; linear kappa 0.604; High recall 67.6%; under-triage 17.9% (95% CI 11.1%-24.8%); over-triage 13.7%
  - H (Triage nurse (KTAS_RN)): n=117; accuracy 87.2% (95% CI 80.3%-93.2%); balanced accuracy 87.3%; macro-F1 0.874 (95% CI 0.809-0.929); weighted F1 0.872; linear kappa 0.854; High recall 91.9%; under-triage 6.8% (95% CI 2.6%-12.0%); over-triage 6.0%
- 5-fold CV (5-fold StratifiedKFold (train+validation, test untouched)): S0 macro-F1 0.198 ± 0.001, accuracy 0.421 ± 0.002; S1 macro-F1 0.644 ± 0.032, accuracy 0.652 ± 0.031; S2a macro-F1 0.677 ± 0.057, accuracy 0.685 ± 0.055; S2b macro-F1 0.705 ± 0.021, accuracy 0.713 ± 0.018
- Retrieval quality KB=ktas-train: P@1 0.591, P@3 0.618, P@5 0.611, mean top-1 similarity 0.700, no-evidence rate 2.6%
- Retrieval quality KB=mimic-all: P@1 0.318, P@3 0.319, P@5 0.321, mean top-1 similarity 0.565, no-evidence rate 9.4%
- Subgroup S2b by sex: F n=55 acc 63.6% under 20.0%; M n=62 acc 72.6% under 16.1%
- Subgroup S2b by age_band: 40-64 n=39 acc 61.5% under 12.8%; 65+ n=50 acc 76.0% under 18.0%; <40 n=28 acc 64.3% under 25.0%
- Subgroup H by sex: F n=55 acc 89.1% under 5.5%; M n=62 acc 85.5% under 8.1%
- Subgroup H by age_band: 40-64 n=39 acc 87.2% under 5.1%; 65+ n=50 acc 90.0% under 6.0%; <40 n=28 acc 82.1% under 10.7%

## Prompt change (process fact)
- Prompt v1 = previous release prompt ('assign Low if mild and no red flags; NEVER default to Medium or High')
- Prompt v2 = ESI/KTAS-aligned definitions (high-risk complaints High even with normal vitals; uncertain -> more urgent)
- v2 was written after v1 produced 18/31 'Low' predictions on the MIMIC test split; v2 was checked on the MIMIC validation split before its test run

## Live system facts
- Example local run (High demo case): Agent 2 632 ms, Agent 3 1,224 ms (1,637 tokens), Agent 4 0.1 ms, Agent 5 12 ms (mocked)
- Whisper base.en first transcription incl. model load: 19.3 s on CPU (demo clip, 9 s of speech)
- Weak-evidence banner text: 'Weak historical evidence — treat this recommendation with caution.'
- NEWS2 assumption: room air (supplemental oxygen not captured); SpO2 scale 1

## Limitations (facts)
- MIMIC-IV-ED Demo is small: 207 labelled stays; test split 31 stays from 11 patients; MIMIC Low class has 2 stays in total (1 test)
- KTAS (Korea) and ESI (MIMIC, USA) are different 5-level scales; both mapped to the same 3 tiers
- KB=MIMIC for KTAS is a cross-site, cross-scale transfer
- Groq free tier: 1,000 requests/day, 8,000 tokens/minute; LLM evaluation run over several days with a response cache
- The Hugging Face Space cannot reach a locally running n8n; Space uses direct Twilio / mocked alerts
- Decision support only: every recommendation is reviewed by a clinician
- Retrieval synonym map sends 'blood' -> 'bleed' (e.g. 'blood pressure tablets' matched a GI-bleed case at 0.53)
