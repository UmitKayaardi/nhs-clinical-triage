# PROGRESS — CN7050 final build

Source plan: `CN7050_PLAN.md` (repo root, local). Branch: `feature/cn7050-final`.
Rule: a new session reads this file and continues from the **first unticked box**. Never redo ticked work.
Python: global `Python 3.12.10` (no project venv; all requirements already installed there).

## Status
- **Current step:** WP1 report stage (`evaluation/report.py`: metrics.json, summary.md, figures, CV, subgroups) while LLM day-1 run fills the cache.
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
- [~] Retrieval leakage control implemented (`allowed_stay_ids`, `index=`, `build_index`); unit test still TODO
- [x] Metrics module `evaluation/metrics.py`
- [~] Baselines S0/S1/S2 + tuning in `evaluation/baselines.py` (CV + runner in scripts/evaluate.py TODO)
- [x] LLM cache + budget/resume (`evaluation/llm_cache.py`, throttle 8K TPM, daily-limit stop)
- [x] S3 / S4 / S4-noNEWS2 runners (`evaluation/llm_runner.py`, `evaluation/runner.py::LLM_JOBS`)
- [ ] LLM runs complete (cache full) -- day 1 started 21 Nov 00:30 with `python scripts/evaluate.py --llm-only --max-llm-calls 110` (log: evaluation/cache/run_day1.log). Total needed ~ 31x2 + 117x3 = 413 cases (+repairs). Resume daily with `python scripts/evaluate.py --llm-only --max-llm-calls 120`, then `--all`
- [ ] Subgroup fairness, low-evidence analysis, latency, retrieval quality
- [ ] metrics.json, summary.md, errors_*.csv, figures; copy to report_assets/figures
- [ ] WP1 unit tests

## WP2 — Weak-evidence warning
- [x] `assess_evidence()` + `evaluation/evidence.py`; T=0.50 chosen on MIMIC development OOF (validation-only too noisy, both tables kept); config default 0.50
- [~] fields in response + prompt flag done; yellow banner (UI) TODO

## WP3 — Guardrail repair loop + NEWS2
- [x] Repair loop (`LLM_MAX_REPAIR_ATTEMPTS=2`) in `llm_service.generate_triage_report` (tests TODO)
- [~] NEWS2 scoring + override rules (`app/services/news2.py`, wired into pipeline); tests TODO

## WP4 — Agent trace
- [x] Trace helper + console log format (`app/services/trace.py`)
- [~] `agent_trace` column + schema.py auto-add + endpoint done; Alembic revision TODO
- [ ] Agent Trace UI view

## WP5 — n8n
- [~] Backend n8n client with fallback (`app/services/n8n_service.py`, `triage_routes.dispatch_alert`); tests TODO
- [ ] `n8n/triage_alert_workflow.json` + `n8n/README.md`
- [ ] Live n8n run (student steps)

## WP6 — UI
- [ ] Clinician Intake tab + demo buttons
- [ ] Doctor card additions
- [ ] Evaluation tab
- [ ] Admin / Supervisor tab

## WP7 — Tests, README, SETUP
- [ ] All tests green, new tests added
- [ ] README + SETUP sections

## WP8 — Report assets (facts only)
- [ ] environment.md, agents_table.md, tools_table.md, preprocessing.md, api_interactions.md
- [ ] json_examples/
- [ ] REPORT_FACTS.md, SCREENSHOTS.md

## WP9 — Screenshots, deploy, final checks
- [ ] Playwright screenshots
- [ ] PR → merge → Space deploy → smoke test
- [ ] Final self-check (§12.3)
