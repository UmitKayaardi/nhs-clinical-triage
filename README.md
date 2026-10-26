---
title: NHS Clinical Triage
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
pinned: false
---

# AI-Powered Clinical Triage Assistant

A clinical decision support system (CDSS) for Emergency Departments. A patient describes their symptoms by voice (or a clinician types them), the system retrieves similar historical cases from MIMIC-IV-ED, an LLM proposes a 3-tier triage level (High / Medium / Low) grounded in that evidence, and on-call staff are alerted on WhatsApp for High-priority cases. Clinicians review every decision, and the system monitors its own accuracy, data drift and bias after deployment.

> **Decision support only.** Every output is a draft for clinician review. The system never makes the final triage decision.

**Live demo:** https://huggingface.co/spaces/UmitKayaardi/nhs-clinical-triage

## The 7 agents

```text
 audio ─► [1 Intake/Whisper] ─┐
 typed symptoms + vitals ─────┴► [2 Evidence Retrieval] ─► [3 Clinical Reasoning] ─► [4 Guardrail]
                                   (all 6 MIMIC tables)      (Groq gpt-oss-20b)        (Pydantic)
                                                                                           │
                         TriageSession saved (audit) ◄─────────────────────────────────────┤
                                                                                           ▼
 clinician feedback ─► [6 Post-Deployment Monitor] ─► [7 Drift & Bias Monitor]   [5 WhatsApp alert]
                       accuracy, hallucinations,      KS / Jensen-Shannon /      (Twilio, High only)
                       monthly PMS report             chi-squared, alerts
```

| # | Agent | Code | What it does |
|---|-------|------|--------------|
| 1 | Data Intake & Transcription | `app/services/audio_service.py` | Whisper `base.en` on CPU turns audio into text. Silent or empty audio is rejected with a clear message. A structured endpoint accepts typed symptoms and vitals instead. |
| 2 | Evidence Retrieval | `app/services/retrieval_service.py` | Scores every historical stay across **all six** MIMIC-IV-ED tables and returns the top 5 with diagnoses, vitals, ED treatments and a similarity score in [0, 1]. |
| 3 | Clinical Reasoning | `app/services/llm_service.py` | Groq `openai/gpt-oss-20b` at temperature 0. Returns symptoms, duration, possible conditions, severity, **reasoning** and **required actions**. |
| 4 | Medical Guardrail | `app/schemas/triage_schema.py` | Strict Pydantic `TriageResult` schema. Any LLM output that doesn't validate is rejected (HTTP 502) and never shown to a clinician. |
| 5 | Orchestrator & Action | `app/services/twilio_service.py` | Sends a WhatsApp alert to the on-call doctor via Twilio for High-severity cases. Retries transient errors with exponential backoff and logs every send or failure to `alert_log`. |
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

## API

Interactive docs: `http://localhost:8000/docs`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/process-triage` | Audio upload (`file`) plus optional `patient_id`, `age`, `gender` (`M`/`F`), `ethnicity` form fields |
| POST | `/api/v1/process-triage/structured` | JSON `{chief_complaint, vitals?, patient_id?, age?, gender?, ethnicity?}` |
| GET | `/api/v1/sessions?severity=High&limit=200` | Dashboard list, newest first, with each session's latest review |
| POST | `/api/v1/feedback` 🔒 | `{session_id, feedback: "correct" \| "incorrect", notes?, reviewed_by?}` |
| GET | `/api/v1/admin/accuracy` 🔒 | `{accuracy_30d, hallucination_rate, trend, accuracy_by_severity, ...}` |
| GET | `/api/v1/admin/flagged` 🔒 | Sessions whose latest review is "incorrect" |
| GET | `/api/v1/admin/pms-report?month=YYYY-MM` 🔒 | Monthly PMS CSV: `date, total_sessions, reviewed, correct, hallucinations, accuracy_%, alerts` |
| GET | `/api/v1/admin/drift` 🔒 | `{drift_score, drift_detected, bias_detected, bias_scores_by_demographic, trend_graph_data, alerts}`. Stores a `drift_metrics` snapshot unless `persist=false` |
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
```

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

44 tests cover retrieval ranking and synonyms, Twilio retry, mock and failure logging, feedback and accuracy maths, the monthly report, drift/bias statistics, and the full API flow (audio → triage → alert → feedback → accuracy). Whisper, Groq and Twilio are mocked, so no network access, GPU or credentials are needed and no WhatsApp message is ever sent.

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
| `DOCTOR_PORTAL_PIN` | yes | Change from the default |
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
│   └── services/        audio, retrieval, llm, twilio, alert, monitoring, drift
├── alembic/             migrations
├── data/                MIMIC-IV-ED demo CSV subset
├── scripts/             import_mimic_csv.py, seed_monitoring_demo.py
├── tests/               unit + integration tests
├── app.py               Gradio UI (Patient Kiosk + Doctor Portal) + embedded API
└── Dockerfile, docker-compose.yml, requirements.txt, .env.example
```

## Data

The system uses the de-identified MIMIC-IV-ED demo subset: `edstays`, `triage`, `diagnosis`, `vitalsign`, `medrecon`, `pyxis`. MIMIC timestamps are date-shifted, so they don't reflect real dates.
