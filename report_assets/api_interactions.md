# External and internal interfaces (facts only)

## External services

| Service | Protocol | Method | Endpoint | Auth | Request format | Response format |
|---|---|---|---|---|---|---|
| Groq (Agent 3) | HTTPS REST (OpenAI-compatible) | POST | `https://api.groq.com/openai/v1/chat/completions` | `Authorization: Bearer <GROQ_API_KEY>` (from env, never logged) | JSON: `model`, `messages[system,user(,assistant,user for repairs)]`, `temperature 0`, `max_tokens 1024`, `response_format {"type":"json_object"}`, `reasoning_effort "low"` — see `json_examples/groq_request.json` | JSON: `choices[0].message.content` (string containing the triage JSON), `usage` tokens — see `json_examples/groq_response.json` |
| Groq (health check) | HTTPS REST | GET | `/openai/v1/models` | Bearer key | — | model list (no token cost) |
| Whisper (Agent 1) | in-process Python call (local model, no network) | — | `whisper.load_model("base.en").transcribe(path, fp16=False)` | — | audio file path (ffmpeg-decoded) | dict with `text` |
| n8n (Agent 5) | HTTP REST webhook | POST | `http://localhost:5678/webhook/triage-alert` (`N8N_WEBHOOK_URL`) | header `X-Webhook-Secret` | JSON event — `json_examples/n8n_webhook_request.json` | JSON `{status, channel, message_sid}` or 401 — `json_examples/n8n_webhook_response.json` |
| Twilio (from n8n or direct fallback) | HTTPS REST | POST | `https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json` (SDK `messages.create`) | HTTP Basic (Account SID + Auth Token) | form fields `From=whatsapp:+...`, `To=whatsapp:+...`, `Body=<alert text>` — `json_examples/twilio_message.json` | message resource with `sid` (SM...) |
| SMTP (Agent 7 critical alerts, optional) | SMTP + STARTTLS | — | `SMTP_HOST:587` | username/password | plain-text email | — |
| Hugging Face Space | HTTPS | — | `https://huggingface.co/spaces/UmitKayaardi/nhs-clinical-triage` | Space secrets | — | Gradio UI |

## Own FastAPI endpoints (`http://127.0.0.1:8000`, OpenAPI at `/docs`)

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| POST | `/api/v1/process-triage` | — | multipart: `file` (audio) + optional `patient_id`, `age`, `gender` (M/F), `ethnicity` | `TriageReportResponse` JSON (see `json_examples/triage_response.json`) |
| POST | `/api/v1/process-triage/structured` | — | JSON `{chief_complaint, vitals{temperature F, heart_rate, resp_rate, o2sat, sbp, dbp, pain, consciousness}, age, gender, arrival_mode, injury, patient_id, ethnicity}` | `TriageReportResponse` JSON |
| GET | `/api/v1/sessions?severity=&limit=` | — | query | `{status, count, total, data[...]}` incl. evidence_scores, evidence_strength, news2_score, safety_override, has_trace |
| GET | `/api/v1/sessions/{session_id}/trace` | — | path | `{session_id, created_at, severity, intake_mode, steps[...], count}` |
| POST | `/api/v1/feedback` | `X-Admin-Key` when set | `{session_id, feedback: correct|incorrect, notes?, reviewed_by?}` | 201 `{id, session_id, feedback, flagged_for_review, timestamp}` |
| GET | `/api/v1/admin/accuracy` | `X-Admin-Key` | `window_days?` | accuracy JSON |
| GET | `/api/v1/admin/flagged` | `X-Admin-Key` | `limit?` | flagged sessions |
| GET | `/api/v1/admin/pms-report?month=YYYY-MM` | `X-Admin-Key` | query | `text/csv` |
| GET | `/api/v1/admin/drift?persist=` | `X-Admin-Key` | query | drift/bias JSON + Agent 7 `trace` |
| GET | `/api/v1/admin/system-health` | `X-Admin-Key` | — | Groq/n8n reachability, Twilio mode, DB row counts, model settings, versions |
| POST | `/api/v1/alerts` | `X-Admin-Key` | `{alert_type, severity, message, session_id?}` | alert JSON incl. `channel` |
| GET | `/api/v1/alerts` | `X-Admin-Key` | `unacknowledged_only?`, `alert_type?`, `limit?` | `{count, data[...]}` |
| POST | `/api/v1/alerts/{id}/acknowledge` | `X-Admin-Key` | — | alert JSON |
| GET | `/health` | — | — | `{status, environment}` |

## Internal agent-to-agent messages

| From -> To | Format |
|---|---|
| Agent 1 -> Agent 2 | transcript string (`json_examples/agent1_*.json`) |
| Agent 2 -> Agent 3 | formatted evidence block (5 numbered cases) + evidence-strength line inside the system prompt (`json_examples/agent2_*.json`) |
| Agent 3 -> Agent 4 | raw model text expected to be one JSON object (`json_examples/agent3_*.json`) |
| Agent 4 -> Agent 3 (repair) | assistant message = rejected output; user message = "The Medical Guardrail rejected your previous output. Validation error: ..." |
| Agent 4 -> persistence / Agent 5 | validated `TriageResult` + NEWS2 result (`json_examples/agent4_*.json`) |
| Agent 5 -> n8n -> Twilio | webhook JSON event -> WhatsApp message |
| Sessions -> Agents 6/7 | SQLite rows (`triage_sessions`, `triage_session_feedback`) |
