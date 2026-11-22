---
title: NHS Clinical Triage
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
pinned: false
---

**Doctor Portal / Admin PIN: 1234** — demo-only PIN for markers. The system holds no real patient data (MIMIC-IV-ED Demo and invented demo cases only).

# AI-Powered Clinical Triage Assistant

A clinical decision support system (CDSS) for Emergency Departments. A patient describes their symptoms by voice (or a clinician types them), the system retrieves similar historical cases from MIMIC-IV-ED, an LLM proposes a 3-tier triage level (High / Medium / Low) grounded in that evidence, and on-call staff are alerted on WhatsApp for High-priority cases. Clinicians review every decision, and the system monitors its own accuracy, data drift and bias after deployment.

> **Decision support only.** Every output is a draft for clinician review. The system never makes the final triage decision.

**Live demo:** https://huggingface.co/spaces/UmitKayaardi/nhs-clinical-triage

## The 7 agents

```text
 audio ─► [1 Intake/Whisper] ─┐
 typed symptoms + vitals ─────┴► [2 Evidence Retrieval] ─► [3 Clinical Reasoning] ⇄ [4 Guardrail]
                                   (all 6 MIMIC tables,      (Groq gpt-oss-20b)      (Pydantic schema,
                                    evidence strength)                                repair loop, NEWS2)
                                                                                           │
                         TriageSession + agent trace saved ◄───────────────────────────────┤
                                                                                           ▼
 clinician feedback ─► [6 Post-Deployment Monitor] ─► [7 Drift & Bias Monitor]   [5 Orchestrator]
                       accuracy, hallucinations,      KS / Jensen-Shannon /      n8n webhook → Twilio
                       monthly PMS report             chi-squared, alerts        WhatsApp (High only)
```

| # | Agent | Code | What it does |
|---|-------|------|--------------|
| 1 | Data Intake & Transcription | `app/services/audio_service.py` | Whisper `base.en` on CPU turns audio into text. Silent or empty audio is rejected with a clear message. A structured endpoint accepts typed symptoms and vitals instead. |
| 2 | Evidence Retrieval | `app/services/retrieval_service.py` | Scores every historical stay across **all six** MIMIC-IV-ED tables and returns the top 5 with diagnoses, vitals, ED treatments and a similarity score in [0, 1]. |
| 3 | Clinical Reasoning | `app/services/llm_service.py` | Groq `openai/gpt-oss-20b` at temperature 0. Returns symptoms, duration, possible conditions, severity, **reasoning** and **required actions**. |
| 4 | Medical Guardrail | `app/schemas/triage_schema.py`, `app/services/llm_service.py`, `app/services/news2.py` | Strict Pydantic `TriageResult` schema. A rejected draft goes back to Agent 3 with the validation error (max 2 repairs, then HTTP 502). The NEWS2 safety net can raise, never lower, the severity. |
| 5 | Orchestrator & Action | `app/services/n8n_service.py`, `n8n/`, `app/services/twilio_service.py` | High-severity cases go to the n8n workflow (webhook → secret check → Twilio WhatsApp). If n8n is not configured or unreachable, Twilio is called directly. The channel (`n8n`, `twilio_direct`, `mocked`) is logged in `alert_log`. |
| 6 | Post-Deployment Monitor | `app/services/monitoring_service.py` | Clinicians mark sessions correct or incorrect. Computes 30-day accuracy and hallucination rate, keeps a review queue of flagged sessions, and produces the monthly PMS CSV. |
| 7 | Drift & Bias Monitor | `app/services/drift_service.py` | Detects performance drift, data drift and bias. Raises alerts and emails the admin. |

### Agent 2: how retrieval scores a case

Each historical stay gets a weighted score:

| Component | Source tables | Weight |
|-----------|---------------|--------|
| Chief complaint | `triage.csv` | 1.0 (a complaint whose every word the patient said counts as an exact match = 1.0) |
| Diagnoses | `diagnosis.csv` | 0.7 |
| Vitals | `triage.csv`, `vitalsign.csv` (mean) | 0.5 (only when vitals are supplied) |
| Medications | `medrecon.csv`, `pyxis.csv` | 0.3 |
| Stay / disposition | `edstays.csv` | context returned to the LLM |

Text similarity is TF-IDF cosine after clinical normalisation. MIMIC abbreviations (`SOB`, `N/V`, `ABD PAIN`, `S/P FALL`) and lay phrasing ("can't catch my breath", "stomach", "threw up") map onto shared tokens. This is deliberately lexical rather than a neural embedding model: the Space stays CPU-only and every match can be explained. Vitals similarity uses a Gaussian kernel on clinically scaled differences. Weights can be changed with the `RETRIEVAL_WEIGHT_*` settings.

### Agent 7: what is tested

| Check | Method | Alert when |
|-------|--------|------------|
| Performance drift | Clinician-reviewed accuracy over 30 days, plus first-half vs second-half comparison | accuracy < 85% (at least 10 reviews) **or** a drop of more than 5 points |
| Data drift | Jensen-Shannon distance (the bounded, symmetric form of KL divergence) of gender, ethnicity and severity mix vs the MIMIC reference; Kolmogorov-Smirnov test on age vs the previous 90 days | `drift_score` (largest per-feature score) > 0.3 |
| Bias | Chi-squared test of independence on severity × group and on correct/incorrect × group, for gender, age band and ethnicity; Cramér's V as effect size | p < 0.05 |

Severity genuinely differs with age, so an age × severity association is reported but not flagged as bias. An **error** disparity (the model is wrong more often for one group) is flagged for every demographic. Each alert type is raised at most once per 24 hours. Critical alerts are emailed when SMTP is configured.

### Weak-evidence warning (WP2)

After retrieval, Agent 2 rates the evidence: **weak** when the top-1 similarity is below `LOW_EVIDENCE_THRESHOLD` (0.50, selected on non-test data only — out-of-fold over the 114 training + 62 development stays — and frozen before the held-out run), **strong** when top-1 and mean top-5 similarity are both above it and at least 60% of the cases agree on the severity, otherwise **moderate**. Weak evidence is written into the LLM prompt (the model must say so and may not report High confidence), and the doctor's card shows a yellow banner: *Weak historical evidence — treat this recommendation with caution.*

### Safety net (NEWS2)

Agent 4 computes the NHS **NEWS2** score (RCP 2017 chart) from respiratory rate, SpO2 (scale 1), systolic BP, pulse, temperature and consciousness when known. Supplemental oxygen is not captured, so room air is assumed. Rules: NEWS2 ≥ 7 or any single parameter scoring 3 → at least **High**; NEWS2 5–6 → at least **Medium**. The safety net only raises severity. The response and the card show `news2_score`, `safety_override` and `override_reason`; `llm_severity` keeps Agent 3's original answer.

### Agent trace

Every request records one step per agent (input, output, status, duration, which agent receives the output). It is returned in the response as `trace`, stored in `triage_sessions.agent_trace`, served by `GET /api/v1/sessions/{id}/trace`, shown in the Doctor Portal's **Agent Trace** panel, and logged like this:

```text
[Agent 2 | Evidence Retrieval] 5 cases, top similarity 0.77, evidence strong, 631.8 ms (ok)
[Agent 3 | Clinical Reasoning] attempt 1, 1637 tokens, 1223.7 ms (ok)
[Agent 4 | Medical Guardrail] schema valid on attempt 1, 0.1 ms (ok)
[Agent 4 | Medical Guardrail (NEWS2 safety net)] NEWS2 6, final severity High, 0.1 ms (ok)
[Agent 5 | Orchestrator & Action] mocked -> mocked, 11.5 ms (mocked)
```

Clinician feedback (Agent 6) appends its own step to the session trace; a drift run (Agent 7) returns a trace step too.

### n8n orchestration

`n8n/triage_alert_workflow.json` is an importable n8n workflow: Webhook (`POST /webhook/triage-alert`) → check `X-Webhook-Secret` → IF severity is High → IF test mode → Twilio WhatsApp node or "mocked" → Respond `{status, channel, message_sid}`. Set `N8N_WEBHOOK_URL` and `N8N_WEBHOOK_SECRET` to use it; timeout 5 s, 2 retries, then direct Twilio. Setup steps: [`n8n/README.md`](n8n/README.md). The Hugging Face Space cannot reach a local n8n, so the Space uses the direct Twilio path.

## Evaluation

```bash
python scripts/evaluate.py --all              # everything; LLM calls are cached and budgeted (--max-llm-calls)
python scripts/evaluate.py --all --offline    # reproduce every number from the committed cache, no API calls
```

- MIMIC protocol: prompt v1 → v2 was developed on a **development set** (62 stays, 26 patients). The configuration (prompt v2, retrieval weights, k, evidence threshold, repair attempts, NEWS2) was then **frozen** (`evaluation/frozen_config.json`; held-out runs refuse to start if it changes) and evaluated **once** on a new **held-out test split** (31 stays, 9 patients that were never an LLM query; `evaluation/splits/mimic_split_v2.json`). Training / knowledge base: the remaining 114 stays (21 patients). No patient is in two sets.
- KTAS: stratified 70/15/15 (886/190/191), external evaluation with the frozen prompt v2. Seed 42 everywhere.
- Leakage control: during MIMIC evaluation the evidence index holds training stays only (`find_similar_cases(..., allowed_stay_ids=...)` / `index=`); a test proves a test stay never retrieves itself.
- Systems: S0 majority, S1 retrieval-only vote, S2a logistic regression, S2b random forest, S3 LLM without evidence, **S4 full system**, S4-noNEWS2, S4-promptv1 (previous prompt), H triage nurse (KTAS).
- Metrics: accuracy, balanced accuracy, precision/recall/F1 (macro, weighted, per class), confusion matrices, linear-weighted kappa, under-/over-triage, High recall, ROC-AUC, 95% bootstrap CIs, 5-fold CV, McNemar, retrieval P@k, latency per agent, guardrail repair rate, NEWS2 overrides, weak-evidence analysis, subgroups by sex and age band.
- Outputs: `evaluation/results/metrics.json`, `summary.md`, `errors_*.csv`, figures in `evaluation/results/figures/` (also in `report_assets/figures/`), and the **Evaluation** tab of the app.
- Groq free tier limits (about 200K tokens/day) mean the LLM runs are spread over several days; every call is cached in `evaluation/cache/llm_cache.jsonl`, and a stopped run prints the command to resume.

Headline numbers: see `evaluation/results/summary.md` (regenerated by the command above).

## Datasets

| Dataset | Use | Size | Labels |
|---|---|---|---|
| MIMIC-IV-ED Demo v2.2 (`data/*.csv`, loaded into `triage_data.db`) | Knowledge base for Agent 2 + internal evaluation | 64 patients, 222 ED stays, 207 with ESI acuity | ESI 1–2 High (115), 3 Medium (90), 4–5 Low (2) |
| KTAS, Moon et al. (2019) *PLoS ONE* 14(9) e0216972 (`data/external/ktas/`, CC BY 4.0) | External validation only, never loaded by the live system | 1,267 adult ED visits, 2 Korean EDs | `KTAS_expert` (truth): High 246, Medium 487, Low 534; `KTAS_RN` = nurse baseline |

`python -m scripts.download_ktas` re-downloads the KTAS file from the journal and checks its SHA-256. Cleaning steps and row counts: `report_assets/preprocessing.md`.

## API

Interactive docs: `http://localhost:8000/docs`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/process-triage` | Audio upload (`file`) plus optional `patient_id`, `age`, `gender` (`M`/`F`), `ethnicity` form fields |
| POST | `/api/v1/process-triage/structured` | JSON `{chief_complaint, vitals?, patient_id?, age?, gender?, ethnicity?}` |
| GET | `/api/v1/sessions?severity=High&limit=200` | Dashboard list, newest first, with each session's latest review, evidence strength, NEWS2 and override flags |
| GET | `/api/v1/sessions/{id}/trace` | Step-by-step agent trace of one session |
| POST | `/api/v1/feedback` 🔒 | `{session_id, feedback: "correct" \| "incorrect", notes?, reviewed_by?}` |
| GET | `/api/v1/admin/accuracy` 🔒 | `{accuracy_30d, hallucination_rate, trend, accuracy_by_severity, ...}` |
| GET | `/api/v1/admin/flagged` 🔒 | Sessions whose latest review is "incorrect" |
| GET | `/api/v1/admin/pms-report?month=YYYY-MM` 🔒 | Monthly PMS CSV: `date, total_sessions, reviewed, correct, hallucinations, accuracy_%, alerts` |
| GET | `/api/v1/admin/drift` 🔒 | `{drift_score, drift_detected, bias_detected, bias_scores_by_demographic, trend_graph_data, alerts}`. Stores a `drift_metrics` snapshot unless `persist=false` |
| GET | `/api/v1/admin/system-health` 🔒 | Groq and n8n reachability, Twilio mode, DB row counts, model settings, versions |
| POST | `/api/v1/alerts` 🔒 | `{alert_type, severity: info\|warning\|critical, message, session_id?}` |
| GET | `/api/v1/alerts` 🔒 | Alert log. `POST /api/v1/alerts/{id}/acknowledge` marks one handled |
| GET | `/health` | Liveness |

🔒 = requires header `X-Admin-Key` when `ADMIN_API_KEY` is set. Unexpected errors return a generic `{"error": "Internal server error"}`. Details go to the server log only.

## Database

The MIMIC reference tables are `ed_stays`, `triage`, `diagnoses`, `med_reconciliations`, `pyxis_medications` and `vital_signs`. Live tables:

- `triage_sessions`: one row per triage, with transcript, structured output, reasoning, evidence stay IDs and scores, and optional demographics.
- `triage_session_feedback`: `session_id, feedback, feedback_notes, reviewed_by, flagged_for_review, timestamp`.
- `alert_log`: `session_id, alert_type, severity, message, status, external_id, timestamp, acknowledged`.
- `drift_metrics`: `timestamp, accuracy_30d, hallucination_rate, drift_score, bias_by_demographic, retraining_needed`.

On startup, `app/db/schema.py` creates any missing tables and adds missing nullable columns. This is how the Space's bundled `triage_data.db` gets upgraded without data loss. Postgres deployments should use `alembic upgrade head`; revision `c7d1e2f3a4b5` adds the monitoring schema.

## Local setup

```bash
git clone https://github.com/UmitKayaardi/nhs-clinical-triage.git
cd nhs-clinical-triage
pip install -r requirements.txt          # Whisper also needs ffmpeg on PATH
cp .env.example .env                     # then fill in GROQ_API_KEY etc.
python app.py                            # Gradio UI on :7860, FastAPI on :8000
python scripts/run_local_demo.py         # same, but on a throwaway copy of the database (.local/demo.db)
```

The **Clinician Intake** tab has demo buttons (High, Medium, Low, Weak evidence, NEWS2 safety net) with invented examples; `demo/demo_patient_chest_pain.wav` is a synthetic voice clip for the Patient Kiosk (upload it in the audio box).

To rebuild the database from the CSVs: `python setup_db.py && python -m scripts.import_mimic_csv --data-dir data`.

To see the monitoring dashboards with data (local or demo databases only, never with real patient sessions):

```bash
python -m scripts.seed_monitoring_demo --sessions 30 --accuracy 0.8
python -m scripts.seed_monitoring_demo --purge
```

### Tests

```bash
pytest
```

121 tests cover retrieval ranking and synonyms, leakage control, Twilio retry, mock and failure logging, n8n success/failure/fallback, the guardrail repair loop, the NEWS2 chart, the agent trace, feedback and accuracy maths, the monthly report, drift/bias statistics, the evaluation metrics, splits and KTAS cleaning, the LLM cache, and the full API flow (audio → triage → alert → feedback → accuracy). Whisper, Groq, Twilio and n8n are mocked, so no network access, GPU or credentials are needed and no WhatsApp message is ever sent.

### Docker (PostgreSQL)

```bash
cp .env.example .env    # set GROQ_API_KEY, ADMIN_API_KEY, POSTGRES_PASSWORD, Twilio vars
docker compose up -d db
alembic upgrade head
python -m scripts.import_mimic_csv --data-dir data
docker compose up -d api
```

## Deploying to Hugging Face

The Space runs `app.py`, which starts FastAPI in a background thread and serves the Gradio UI. Set these under **Settings → Variables and secrets**. Never commit a `.env` file.

| Secret | Required | Notes |
|--------|----------|-------|
| `GROQ_API_KEY` | yes | |
| `DATABASE_URL` | no | Defaults to `sqlite:///./triage_data.db` (the bundled database) |
| `DOCTOR_PORTAL_PIN` | recommended | Demo default `1234` (kept for markers; no real patient data) |
| `ADMIN_PORTAL_PIN` | optional | Admin / Supervisor tab PIN; defaults to `DOCTOR_PORTAL_PIN` |
| `LLM_REASONING_EFFORT` | optional | Default `low` |
| `LLM_PROMPT_VERSION` | optional | Default `v2` |
| `N8N_WEBHOOK_URL`, `N8N_WEBHOOK_SECRET` | no | Leave unset on the Space (it cannot reach a local n8n) |
| `ADMIN_API_KEY` | recommended | Protects feedback and admin endpoints. The Gradio app forwards it automatically |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `DOCTOR_WHATSAPP_NUMBER` | for live alerts | Without them, alerts are logged as `mocked` |
| `TWILIO_TEST_MODE` | optional | `true` forces mocking even with credentials |
| `ADMIN_EMAIL`, `SMTP_*` | optional | Email for critical monitoring alerts |

Note: Space storage is ephemeral unless persistent storage is enabled, so sessions, feedback and alerts written to `triage_data.db` are lost on restart. For real use, point `DATABASE_URL` at a managed Postgres.

## Project structure

```text
├── app/
│   ├── api/v1/          triage_routes.py (Agents 1-5), monitoring_routes.py (Agents 6-7)
│   ├── core/            config.py, security.py (X-Admin-Key)
│   ├── db/              base.py, session.py, schema.py (startup schema bootstrap)
│   ├── models/          mimic_models.py, monitoring_models.py
│   ├── schemas/         triage_schema.py (Agent 4 guardrail), monitoring_schema.py
│   └── services/        audio, retrieval, llm, triage_pipeline, news2, vitals, trace, n8n, twilio, alert, monitoring, drift
├── alembic/             migrations
├── data/                MIMIC-IV-ED demo CSV subset; external/ktas/ (KTAS validation data + SOURCE.md)
├── evaluation/          offline evaluation package (splits, metrics, baselines, LLM cache, results)
├── n8n/                 Agent 5 workflow JSON + setup guide
├── report_assets/       facts, tables, JSON examples, figures, screenshots for the report
├── demo/                synthetic demo audio clip
├── scripts/             evaluate.py, download_ktas.py, run_local_demo.py, build_report_assets.py, import_mimic_csv.py, seed_monitoring_demo.py
├── tests/               unit + integration tests
├── app.py               Gradio UI (Patient Kiosk, Clinician Intake, Doctor Portal, Evaluation, Admin) + embedded API
└── Dockerfile, docker-compose.yml, requirements.txt, .env.example
```

## Data

The system uses the de-identified MIMIC-IV-ED demo subset: `edstays`, `triage`, `diagnosis`, `vitalsign`, `medrecon`, `pyxis`. MIMIC timestamps are date-shifted, so they don't reflect real dates.
