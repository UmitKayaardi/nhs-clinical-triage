# Agents (facts only)

Agent names are exactly those of the submitted workflow (Umit_Kayaardi_3231603_Workflow.pdf).

| # | Agent | Function | Dataset / input | Output | Talks to | Code |
|---|---|---|---|---|---|---|
| 1 | Data Intake & Transcription Agent | Speech-to-text of the patient recording; rejects empty/silent audio. Structured intake skips transcription. | Audio file (.wav .mp3 .m4a .ogg .webm .flac) via `POST /api/v1/process-triage`; or JSON via `POST /api/v1/process-triage/structured` | Transcript text (`{"transcript": "...", "characters": n}`) | Agent 2 | `app/services/audio_service.py` |
| 2 | Evidence Retrieval Agent | Scores every historical ED stay (TF-IDF cosine on complaint, diagnoses, medications + Gaussian vitals kernel), returns top 5; rates evidence strength (WP2) | Transcript / complaint + optional vitals; MIMIC-IV-ED Demo tables triage, diagnosis, vitalsign, medrecon, pyxis, edstays (222 stays) | 5 cases with similarity 0-1, `evidence_strength` strong/moderate/weak, `low_evidence`, `top_similarity` | Agent 3 | `app/services/retrieval_service.py` |
| 3 | Clinical Reasoning Agent | Groq `openai/gpt-oss-20b` drafts the triage report from statement + structured data + evidence; prompt v2 (ESI/KTAS definitions) | System prompt with evidence block + evidence-strength line; user message with statement and structured intake data | JSON draft: Symptoms, Duration, Possible_Conditions, Severity, Confidence, Reasoning, Required_Actions | Agent 4 | `app/services/llm_service.py` |
| 4 | Medical Guardrail Agent | (a) Pydantic `TriageResult` schema + non-empty reasoning + severity present; on failure sends error + rejected output back to Agent 3 (max 2 repairs, then HTTP 502). (b) NEWS2 safety net: raise-only severity floor | Agent 3 draft; vitals and consciousness | Validated report; `llm_severity`, `news2_score`, `safety_override`, `override_reason`, `guardrail_attempts` | Agent 3 (repair), persistence, Agent 5 | `app/services/llm_service.py`, `app/services/news2.py`, `app/schemas/triage_schema.py` |
| 5 | Orchestrator & Action Agent | For severity in `ALERT_ON_SEVERITIES` (High): POST event to n8n webhook; fallback direct Twilio WhatsApp; `mocked` in test mode | Final severity, complaint, reasoning, NEWS2, session id | Alert outcome `{status, channel, message_sid}`; `alert_log` row | n8n -> Twilio -> on-call phone | `app/api/v1/triage_routes.py::dispatch_alert`, `app/services/n8n_service.py`, `app/services/twilio_service.py`, `n8n/triage_alert_workflow.json` |
| 6 | Post-Deployment Monitor Agent | Clinician correct/incorrect verdicts -> 30-day accuracy, hallucination rate, flagged queue, monthly PMS CSV | `triage_session_feedback`, `triage_sessions` (SQLite) | `/admin/accuracy`, `/admin/flagged`, `/admin/pms-report`; trace step appended to the session | Agent 7, admin | `app/services/monitoring_service.py` |
| 7 | Drift Detection & Bias Monitor Agent | Performance drift, data drift (Jensen-Shannon, KS), bias (chi-squared, Cramér's V); raises alerts | Session logs (30-day window), MIMIC reference distribution, feedback | `/admin/drift` JSON (drift_score, bias_scores_by_demographic, alerts, trace) ; `drift_metrics` row | Alert log, admin | `app/services/drift_service.py` |

## How the system is started (triggers)

| Trigger | Entry point | Agents run |
|---|---|---|
| Patient records audio in **Patient Kiosk** tab | Gradio -> `POST /api/v1/process-triage` (multipart) | 1 -> 2 -> 3 -> 4 -> persist -> 5 |
| Clinician fills **Clinician Intake** tab (or demo button) | Gradio -> `POST /api/v1/process-triage/structured` (JSON) | 1 (structured) -> 2 -> 3 -> 4 -> persist -> 5 |
| Any HTTP client | Same endpoints, see `/docs` | same |
| Clinician saves a review (Doctor Portal) | `POST /api/v1/feedback` | 6 |
| Supervisor runs monitoring (Doctor Portal / Admin tab) | `GET /api/v1/admin/accuracy`, `GET /api/v1/admin/drift` | 6, 7 |
| Process start | `python app.py` (Space) or `python scripts/run_local_demo.py` (local copy of DB) | FastAPI :8000 thread + Gradio :7860 |

## Possible outputs to the user

| Output | Where |
|---|---|
| Kiosk confirmation with reference ID | Patient Kiosk |
| Colour-coded report card: severity (High red / Medium yellow / Low green), confidence, symptoms, duration, conditions, reasoning, required actions | Clinician Intake, Doctor Portal |
| Evidence-strength badge; yellow banner "Weak historical evidence — treat this recommendation with caution." | card |
| NEWS2 badge; red "Safety net override" note with reason | card |
| Top-5 historical cases with similarity | card |
| Agent Trace: one card per agent (input, action, output, time, status) + raw JSON | Clinician Intake accordion, Doctor Portal |
| WhatsApp alert (High) | on-call phone (n8n or Twilio) / `mocked` |
| HTTP 502 when no draft passes the guardrail after 2 repairs; HTTP 422 for silent audio / invalid input | API |
| Accuracy, hallucination rate, drift, bias, alerts, PMS CSV, system health | Doctor Portal monitoring, Admin / Supervisor tab |
| Evaluation tables and figures | Evaluation tab |
