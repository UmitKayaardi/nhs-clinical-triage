# PROGRESS — CN7050 final build

Source plan: `CN7050_PLAN.md` (repo root, local). Branch: `feature/cn7050-final`.
Rule: a new session reads this file and continues from the **first unticked box**. Never redo ticked work.
Python: global `Python 3.12.10` (no project venv; all requirements already installed there).

## Status
- **Current step (22 Nov 2026, KB change):** multi-source knowledge base implemented (student instruction, decided before any result of the affected KTAS jobs). Live KB = 222 MIMIC-IV-ED stays + 1,267 KTAS records (`data/external/ktas/ktas_kb.csv`, `scripts/build_ktas_kb.py`, `KB_INCLUDE_KTAS`); evaluation KB for KTAS main = 222 MIMIC + 886 KTAS train (leak guard `runner.kb_frame`). Source label on every retrieved case (API, trace, UI, LLM text only for multi-source KBs). KTAS = main evaluation (191 test cases). Frozen hash unchanged; `knowledge_base` block + history entry in `evaluation/frozen_config.json`. Day-3 batch next. Do NOT redeploy the Space until every LLM job is complete.
- **Daily routine (student asks each day):** `git checkout feature/cn7050-final` -> `python scripts/evaluate.py --llm-only --max-llm-calls 120` -> `python scripts/evaluate.py --all --offline` -> `python scripts/build_report_assets.py` -> `python -m pytest -q` -> commit + push to GitHub (no Space deploy). Report remaining cases.
- **After the last LLM job:** same rebuild, PR feature -> main, merge, redeploy Space once (space-deploy snapshot: `git checkout space-deploy && git checkout main -- . && git add -A && git add --renormalize . && git commit && git push space space-deploy:main`), smoke test; then Twilio sandbox help.
- **LLM job order (`evaluation/runner.py::LLM_JOBS`):** ktas:S4:kb=mimic+ktas-train (191) -> ktas:S3:kb=none (191) -> ktas:S4:kb=mimic-all (117 sample, 28 cached) -> ktas:S4:kb=mimic-all:extension (other 74, REQUIRED since the student decision of 22 Nov, merged into the base job when complete -> all three KTAS LLM jobs on the same 191 cases). MIMIC held-out jobs are complete and are not re-run.
- **Day-3 batch (22 Nov, after the KB change):** 62 API calls (95,108 tokens, ~1,534/call), then Groq 429 tokens-per-day (rolling 24 h window still held the day-2 batch). KTAS S4 kb=mimic+ktas-train 62/191. Partial KTAS numbers are NOT representative: test rows keep the file order and the nurse is 62.9% on the first 62 test cases vs 87.9% on all 191 -- compare systems only on the same cases, final numbers only at 191.
- **Day-4 batch (24 Nov):** 120 API calls, 182,091 tokens (~1,517/call); KTAS S4 kb=mimic+ktas-train 182/191 (0 failed). Partial numbers still not final (file order).
- **Day-5 batch (26 Nov):** 120 API calls, 143,780 tokens. KTAS main S4 kb=mimic+ktas-train COMPLETE 191/191 (0 failed): acc 60.2% [53.4, 67.0], macro-F1 0.603, High recall 81.1%, under-triage 15.2%, over-triage 24.6%; S4-noNEWS2 61.8% (3 NEWS2 overrides, all to a wrong higher level); weak flag 18 cases acc 38.9% vs 173 acc 62.4%; evidence sources KTAS 89.5% / MIMIC 10.5%. Nurse 88.0%, S2b 70.7% (McNemar S4 vs S2b p=0.015, vs H p<0.001). KTAS S3 114/191.
- **Day-6 batch (27 Nov):** 120 API calls, 164,531 tokens. KTAS S3 COMPLETE 191/191 (0 failed): acc 60.7% [53.4, 67.5], macro-F1 0.613, High recall 78.4%, under-triage 15.2%, over-triage 24.1%. McNemar S4 (multi-source KB) vs S3 on 191: 24 vs 25, p=1.00. KTAS S4 kb=mimic-all 80/117.
- **Day-7 batch (28 Nov):** 100 API calls, 167,372 tokens. **ALL LLM RUNS COMPLETE** (759/759 cases; cache 744 entries, 10 of them unused development-phase S3 calls). Live config matches frozen.
- **Final KTAS (191 test cases, 0 failures in any job):** S4 multi-source KB acc 60.2% [53.4, 67.0], macro-F1 0.603, High recall 81.1%, under 15.2%; S4-noNEWS2 61.8%; S3 60.7% / 0.613 / 78.4% / 15.2%; S4 KB=MIMIC-only (117 + 74 extension) 61.8% / 0.609 / 86.5% / 12.0%; nurse 88.0%; S2b 70.7%. McNemar: multi-source vs MIMIC-only 15 vs 18 p=0.73; vs S3 24 vs 25 p=1.00; vs S2b p=0.015; vs nurse p<0.001.
- **Next:** PR feature -> main, merge, redeploy Space once (space-deploy snapshot), smoke test; then Twilio sandbox help.
- **MIMIC protocol v2 (student instruction, 21 Nov):** old validation + old test = DEVELOPMENT set (62 stays / 26 patients; prompt v1 -> v2 developed here; all LLM results so far are development results). New HELD-OUT test = 31 stays / 9 patients from old-train patients only (`evaluation/splits/mimic_split_v2.json`); train/KB = 114 stays / 21 patients. LLM-free S0-S2 re-tuned on the development set, CV on train + development.
- **Frozen configuration:** `evaluation/frozen_config.json` (sha256 77522c1b1d959477...): prompt v2 + weak rule + repair template hashes, model settings, weights, k=5, LOW_EVIDENCE_THRESHOLD 0.50, agreement 0.6, repairs 2, NEWS2 on. `evaluation/frozen.py::assert_frozen` blocks every held-out/KTAS job if anything differs; every KTAS job uses prompt v2 (test enforces it). NO CHANGES to prompt/threshold/weights after this point.
- **Agent 4 latency fix:** guardrail time is measured per attempt (`guardrail_ms`); Agent 4 latency = guardrail + NEWS2 (was derived by subtracting the cached original API latency -> negative). Test `tests/test_agent_timings.py`. Development-set median now 0.09 ms.
- **Development results (not held-out):** S4 v2 on 62 development stays: acc 59.7%, macro-F1 0.381, High recall 85.3%, under-triage 12.9%. S4-promptv1 on 31 development stays: acc 29.0%, under-triage 64.5%.
- **Held-out LLM-free (MIMIC, 31 stays):** S1 71.0% / under 6.5%; S2a 67.7%; S2b 71.0% / under 12.9%; best by development macro-F1 = S2a.
- **Held-out MIMIC (frozen, run once, 31 stays):** S4 acc 48.4% / High recall 76.5% / under-triage 16.1%; S3 61.3% / 70.6% / 19.4%; S4-promptv1 22.6% / 29.4% / 74.2%; S1 71.0% / 88.2% / 6.5%; S2b 71.0% / 76.5% / 12.9%; McNemar S4 vs S2a p=0.21, S4 vs S3 p=0.22; NEWS2 overrides 0; weak flag: flagged 7 acc 57.1% vs not flagged 24 acc 45.8%.
- **Wording (student, 22 Nov):** "about 1,500 records from two datasets (three emergency departments: one in the USA, two in South Korea)" (README, Evaluation tab, REPORT_FACTS).
- **Tests:** 133 passing (new `tests/test_multi_source_kb.py`).
- **Unused cache entries:** 10 calls of the old (development-phase) S3 job; kept in the cache, not reported.
- **Local helpers:** ffmpeg at `.local/bin/ffmpeg.exe` (imageio-ffmpeg); demo DB copy `.local/demo.db`; demo audio `demo/demo_patient_chest_pain.wav`.

## Phase 0 — pre-flight
- [x] Git: `main` pulled (fast-forward 2 README commits), branch `feature/cn7050-final` created. Remotes: `origin` (GitHub, public), `space` (HF Space).
- [x] Python 3.12.10, requirements already installed globally; `pytest` baseline **44 passed**.
- [x] `.env` exists; `GROQ_API_KEY` set and valid (test call OK, 0.5 s).
- [x] `reasoning_effort` works for `openai/gpt-oss-20b` via `extra_body` (groq SDK 0.13.1 has no kwarg). `low` used 37 vs `medium` 93 completion tokens on the same prompt.
- [x] Groq limits seen in headers: 1,000 requests/day, 8,000 tokens/minute (daily token cap not exposed in headers; plan assumes 200K/day).
- [x] Node v24.14.0, npx 11.9.0 available (n8n via `npx n8n` possible). Docker 29.7.2 installed but daemon not running.
- [x] Space deploy mechanism: local branch `space-deploy` pushed to remote `space` (`space/main`), separate history from GitHub `main`. Space hardware: ZeroGPU (`zero-a10g`), stage RUNNING. No CI workflow.
- [x] Twilio: no `TWILIO_*` keys in `.env`, `TWILIO_TEST_MODE` not set → alerts are `mocked` locally. `ADMIN_API_KEY`, `DOCTOR_PORTAL_PIN`, `N8N_*` not set in `.env`.
- [x] All 4 PDFs present; `docs/coursework/` added to `.gitignore`.
- [x] KTAS source reachable: PLoS ONE Supporting Information S1 (`journal.pone.0216972.s001`, XLSX, sheet `N=1267 data`, 1,267 × 24, SHA-256 `f631c951…beb0`), coding sheet S2. Licence on page: CC BY 4.0. KTAS_expert counts match plan (High 246 / Medium 487 / Low 534). S2 coding: Sex 1=Female, 2=Male; mistriage 1=over, 2=under.
- [x] Other facts: ffmpeg not on PATH (Whisper audio cannot run locally yet); Playwright not installed; MIMIC labelled stays come from 56 of 64 patients; committed DB has 0 triage_sessions.
- [x] Student answers received (21 Nov 2026) → decisions below.

## Decisions (from student answers, 21 Nov 2026)
1. Token removed from `origin` URL (done); student revokes the PAT himself.
2. Full LLM plan (MIMIC test all + KTAS 120 stratified), spread over several days. Order: MIMIC first, then KTAS. Start LLM runs early, keep working on other WPs.
3. n8n via `npx n8n`; give student exact clicks when needed.
4. `TWILIO_TEST_MODE=true` (mocked) for now. After main WPs: help student try Twilio WhatsApp Sandbox (free trial); if it fails stay mocked.
5. Install `imageio-ffmpeg`; create demo audio clip from invented text (Windows TTS).
6. Install Playwright + Chromium.
7. Keep PIN 1234; label in README as demo-only PIN (no real patient data).
8. `CN7050_PLAN.md` git-ignored.
9. Merge PR to `main` and push to Space at end (student types HF token).
10. At the end give the full list of Space secrets/variables.

## WP1 — Offline evaluation
- [x] KTAS download script + `data/external/ktas/` + SOURCE.md (official PLoS S1, CC BY 4.0, committed)
- [x] KTAS cleaning (`evaluation/data.py::load_ktas`): 1,267 rows kept; 19 Korean complaints translated; F/C, C/S expanded; '측불' -> NaN; BT C->F
- [x] MIMIC loader: 207 labelled stays / 56 patients; 1 Celsius temp converted; pain non-numeric -> NaN
- [x] Splits saved: MIMIC 145/31/31 (30/15/11 patients); KTAS 886/190/191. KTAS LLM sample = 117 (High test has only 37)
- [x] Retrieval leakage control (`allowed_stay_ids`, `index=`, `build_index`) + tests (`tests/test_evaluation.py`)
- [x] Metrics module `evaluation/metrics.py`
- [x] Baselines S0/S1/S2 + tuning + 5-fold CV (`evaluation/baselines.py`, `evaluation/report.py`)
- [x] LLM cache + budget/resume (`evaluation/llm_cache.py`, throttle 8K TPM, daily-limit stop)
- [x] S3 / S4 / S4-noNEWS2 runners (`evaluation/llm_runner.py`, `evaluation/runner.py::LLM_JOBS`)
- [x] LLM runs complete (cache full) -- see Status: 444 cases left (protocol v2) -- day 1 started 21 Nov 00:30 with `python scripts/evaluate.py --llm-only --max-llm-calls 110` (log: evaluation/cache/run_day1.log). Total needed ~ 31x2 + 117x3 = 413 cases (+repairs). Resume daily with `python scripts/evaluate.py --llm-only --max-llm-calls 120`, then `--all`
- [x] Subgroup fairness, low-evidence analysis, latency, retrieval quality (code in `evaluation/report.py`; numbers final once LLM runs complete)
- [~] metrics.json, summary.md, errors_*.csv, figures generated (`--all --offline`); regenerate after LLM runs complete
- [x] WP1 unit tests (`tests/test_evaluation.py`, 10 tests)

## WP2 — Weak-evidence warning
- [x] `assess_evidence()` + `evaluation/evidence.py`; T=0.50 chosen on MIMIC development OOF (validation-only too noisy, both tables kept); config default 0.50
- [x] fields in response + prompt flag + yellow banner on cards

## WP3 — Guardrail repair loop + NEWS2
- [x] Repair loop (`LLM_MAX_REPAIR_ATTEMPTS=2`) + tests (`tests/test_guardrail_repair.py`)
- [x] NEWS2 scoring + override rules + chart tests (`tests/test_news2.py`); enum bug on override fixed

## WP4 — Agent trace
- [x] Trace helper + console log format (`app/services/trace.py`)
- [x] `agent_trace` column + schema.py auto-add + Alembic `d8e9f0a1b2c3` + endpoint + tests
- [x] Agent Trace UI view (Doctor Portal accordion + Clinician Intake accordion)

## WP5 — n8n
- [x] Backend n8n client with fallback + tests (`tests/test_n8n_and_trace.py`)
- [x] `n8n/triage_alert_workflow.json` + `n8n/README.md`; verified with real n8n 2.48.7 (mocked/skipped/401) in isolated folder `.local/n8n-test`
- [ ] Live n8n run in student's own n8n + canvas screenshot (student steps in n8n/README.md)

## WP6 — UI
- [x] Clinician Intake tab + 5 demo buttons (High, Medium, Low, Weak evidence, NEWS2 safety net); verified end to end in browser
- [x] Doctor card additions (evidence badge, weak banner, NEWS2, override note, similarity table, trace hint)
- [x] Evaluation tab (reads metrics.json + figures)
- [x] Admin / Supervisor tab (PIN; health, alert log with channel, accuracy/drift/bias, PMS) + `GET /api/v1/admin/system-health`

## WP7 — Tests, README, SETUP
- [x] All tests green: 121 passed
- [x] README + SETUP sections (Evaluation, Datasets, n8n, Agent trace, NEWS2, weak evidence; demo PIN labelled)

## WP8 — Report assets (facts only)
- [x] environment.md, agents_table.md, tools_table.md, preprocessing.md, api_interactions.md (`scripts/build_report_assets.py` regenerates environment + facts)
- [x] json_examples/ (14 files from a real demo session + LLM cache)
- [x] REPORT_FACTS.md generated (rerun `python scripts/build_report_assets.py` after LLM runs) + SCREENSHOTS.md

## WP9 — Screenshots, deploy, final checks
- [x] Playwright screenshots: 16 PNG + console log in `report_assets/screenshots/` (`scripts/take_screenshots.py`; resumable with `--keep-db --demos ...`)
- [x] PR https://github.com/UmitKayaardi/nhs-clinical-triage/pull/2 merged (d2d654c); Space deployed (space/main 9906722, binaries via LFS); smoke test OK (Medium demo case returned a card; Evaluation tab shows tables + 12 figures)
- [~] Final self-check (§12.3) -- see below; open items depend on the remaining LLM runs and student steps

## Final self-check (§12.3) -- 21 Nov 2026
- [x] Every row of the §2 table has its deliverable (1.2 agents_table + trace; 1.3 numbers in REPORT_FACTS; 2.2 WP2/WP3/nurse comparison code; 2.3 tools_table; 3.1 environment.md + json_examples; 3.2 agents_table; 3.3 evaluation/ + preprocessing.md; 4.1 trace + screenshots; 4.2 UI tabs + api_interactions.md; lecturer metrics = Evaluation tab)
- [x] System matches the submitted workflow PDF: 7 agents, n8n (Agent 5), Twilio WhatsApp, Gradio, FastAPI, SQLite, MIMIC-IV-ED 6 tables, Pydantic guardrail, endpoints /process-triage, /feedback, /admin/accuracy, /admin/drift, /admin/pms-report all present
- [~] `python scripts/evaluate.py --all --offline` reproduces all numbers from the cache without API calls -- true for everything cached so far; KTAS LLM systems + MIMIC S3 still to run
- [x] All tests pass (121); no secrets in this branch's history (scanned for gsk_/ghp_/Twilio SID/phone patterns)
- [x] Space works (new build running, demo case + Evaluation tab checked)
- [x] report_assets/ contains no report prose (tables, bullet facts, JSON, figures, screenshots only)
- [ ] Student: revoke the GitHub PAT that was in the old remote URL
- [ ] Student: n8n live run + screenshots S1-S6 (report_assets/SCREENSHOTS.md)
- [ ] Student: check Space secrets (list in final message / README "Deploying to Hugging Face")
