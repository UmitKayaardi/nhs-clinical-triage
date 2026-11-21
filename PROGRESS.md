# PROGRESS — CN7050 final build

Source plan: `CN7050_PLAN.md` (repo root, local). Branch: `feature/cn7050-final`.
Rule: a new session reads this file and continues from the **first unticked box**. Never redo ticked work.
Python: global `Python 3.12.10` (no project venv; all requirements already installed there).

## Status
- **Current step:** WP9 Playwright screenshots (`scripts/take_screenshots.py`), then PR/deploy. LLM runs continue daily.
- **LLM cache status (21 Nov 01:15):** 102 entries. Done: mimic:S4-promptv1 31/31, mimic-val:S4 31/31, mimic:S4 31/31, mimic:S3 10/31. Remaining: mimic:S3 21, ktas:S4 kb=mimic-all 117, ktas:S4 kb=ktas-train 117, ktas:S3 117 (~372 calls, ~3 days). Next day: `python scripts/evaluate.py --llm-only --max-llm-calls 120` then finally `python scripts/evaluate.py --all --offline` and `python scripts/build_report_assets.py`.
- **Local helpers:** ffmpeg at `.local/bin/ffmpeg.exe` (imageio-ffmpeg); demo DB copy `.local/demo.db`; demo audio `demo/demo_patient_chest_pain.wav`.
- **Prompt change (fact for report):** prompt v1 (previous release: 'assign Low if no red flags; NEVER default to Medium/High') under-triaged MIMIC test: acc 0.290, under-triage 0.645, High recall 0.176 (31 stays). Prompt v2 (ESI/KTAS definitions, high-risk complaints stay High, uncertain -> more urgent) written from triage definitions and checked on MIMIC **validation** first: acc 0.581, macro-F1 0.551, under-triage 0.161, High recall 0.882 (31 stays). v2 is default (`LLM_PROMPT_VERSION=v2`); v1 kept as ablation job `mimic:S4-promptv1`. Note: v2 was written after seeing v1 test errors -> state this in the report as a limitation.
- **Tests:** 119 passing (44 original + 75 new).
- **Bug fixed:** empty `CachedCompletion` was falsy -> first 10 calls bypassed the cache (fixed with `is None`).
- **LLM runs (WP1):** not started.

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
- [ ] LLM runs complete (cache full) -- day 1 started 21 Nov 00:30 with `python scripts/evaluate.py --llm-only --max-llm-calls 110` (log: evaluation/cache/run_day1.log). Total needed ~ 31x2 + 117x3 = 413 cases (+repairs). Resume daily with `python scripts/evaluate.py --llm-only --max-llm-calls 120`, then `--all`
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
- [~] REPORT_FACTS.md generated (rerun build_report_assets.py after LLM runs); SCREENSHOTS.md TODO

## WP9 — Screenshots, deploy, final checks
- [ ] Playwright screenshots
- [ ] PR → merge → Space deploy → smoke test
- [ ] Final self-check (§12.3)
