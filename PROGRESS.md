# PROGRESS — CN7050 final build

Source plan: `CN7050_PLAN.md` (repo root, local). Branch: `feature/cn7050-final`.
Rule: a new session reads this file and continues from the **first unticked box**. Never redo ticked work.
Python: global `Python 3.12.10` (no project venv; all requirements already installed there).

## Status
- **Current step:** Phase 0 done — waiting for the student's answers to the pre-flight questions (sent 21 Nov 2026).
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
- [ ] Student answers received → record decisions below.

## Decisions (from student answers)
- (pending)

## WP1 — Offline evaluation
- [ ] KTAS download script + `data/external/ktas/` + SOURCE.md
- [ ] KTAS cleaning module + preprocessing log
- [ ] MIMIC loader (labels via existing `map_acuity_to_severity`)
- [ ] Splits (MIMIC grouped 70/15/15, KTAS stratified 70/15/15) saved to JSON
- [ ] Retrieval leakage control (`allowed_stay_ids` / index from records) + test
- [ ] Metrics module (acc, bal-acc, P/R/F1, CM, kappa, under/over-triage, AUC, bootstrap CI, McNemar)
- [ ] Baselines S0, S1 (tuned k/weights), S2a LR, S2b RF + 5-fold CV
- [ ] LLM cache + budget/resume (`--max-llm-calls`)
- [ ] S3 / S4 / S4-noNEWS2 runners (MIMIC test, KTAS 120 sample, KB=MIMIC and KB=KTAS-train)
- [ ] LLM runs complete (cache full)
- [ ] Subgroup fairness, low-evidence analysis, latency, retrieval quality
- [ ] metrics.json, summary.md, errors_*.csv, figures; copy to report_assets/figures
- [ ] WP1 unit tests

## WP2 — Weak-evidence warning
- [ ] evidence strength + threshold tuned on MIMIC validation (`LOW_EVIDENCE_THRESHOLD`)
- [ ] fields in response + prompt flag + yellow banner

## WP3 — Guardrail repair loop + NEWS2
- [ ] Repair loop (`LLM_MAX_REPAIR_ATTEMPTS=2`)
- [ ] NEWS2 scoring + override rules + tests against official chart

## WP4 — Agent trace
- [ ] Trace helper + console log format
- [ ] `agent_trace` column (schema.py + Alembic) + `GET /api/v1/sessions/{id}/trace`
- [ ] Agent Trace UI view

## WP5 — n8n
- [ ] Backend n8n client with fallback + tests
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
