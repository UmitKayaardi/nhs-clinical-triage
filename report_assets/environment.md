# Development and simulation environment (facts only)

Generated 2026-11-21 by `python scripts/build_report_assets.py`.

## Platform

| Item | Value |
|---|---|
| OS | Windows 11 (10.0.26300) |
| Python | 3.12.10 |
| CPU | AMD Ryzen 7 4800H with Radeon Graphics |
| RAM | 15,4 GB |
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU; AMD Radeon(TM) Graphics (not used: Whisper and torch run on CPU) |
| Node.js | v24.14.0 |
| n8n | 2.48.7 (npx n8n@2.48.7) |
| Deployment | Hugging Face Space, Gradio SDK 5.9.1, hardware ZeroGPU (`zero-a10g`); Dockerfile: python:3.11-slim |

## Python packages (installed versions)

| Package | Version |
|---|---|
| fastapi | 0.115.6 |
| uvicorn | 0.32.1 |
| pydantic | 2.10.3 |
| pydantic-settings | 2.6.1 |
| SQLAlchemy | 2.0.36 |
| alembic | 1.14.0 |
| openai-whisper | 20250625 |
| torch | 2.14.0 |
| groq | 0.13.1 |
| twilio | 9.3.7 |
| requests | 2.32.5 |
| pandas | 2.3.3 |
| numpy | 2.3.5 |
| scipy | 1.16.3 |
| scikit-learn | 1.7.2 |
| matplotlib | 3.10.7 |
| openpyxl | 3.1.5 |
| gradio | 5.0.0 |
| pytest | 8.3.4 |
| httpx | 0.28.1 |
| imageio-ffmpeg | 0.8.1 |
| playwright | 1.65.2 |

## Models and agent parameters

| Parameter | Value | Setting |
|---|---|---|
| Agent 1 speech model | Whisper `base.en`, CPU, fp16=False | `WHISPER_MODEL_NAME` |
| Agent 3 LLM | `openai/gpt-oss-20b` via Groq API | `GROQ_MODEL_NAME` |
| Temperature | 0.0 | `LLM_TEMPERATURE` |
| Max output tokens | 1024 | `LLM_MAX_TOKENS` |
| Reasoning effort | low | `LLM_REASONING_EFFORT` |
| Output format | JSON mode (`response_format={"type":"json_object"}`) | — |
| Prompt version | v2 | `LLM_PROMPT_VERSION` |
| Guardrail repair attempts | 2 | `LLM_MAX_REPAIR_ATTEMPTS` |
| Retrieved cases (k) | 5 | `MAX_SIMILAR_CASES` |
| Retrieval weights complaint/diagnosis/vitals/medication | 1.0/0.7/0.5/0.3 | `RETRIEVAL_WEIGHT_*` |
| Weak-evidence threshold (top-1 similarity) | 0.5 | `LOW_EVIDENCE_THRESHOLD` |
| Evidence label-agreement minimum (strong) | 0.6 | `EVIDENCE_MIN_AGREEMENT` |
| NEWS2 safety net | True | `NEWS2_SAFETY_NET_ENABLED` |
| Alert severities | ['High'] | `ALERT_ON_SEVERITIES` |
| n8n timeout / retries | 5.0 s / 2 | `N8N_TIMEOUT_SECONDS`, `N8N_MAX_RETRIES` |
| Twilio retries / backoff | 3 / 1.0 s exponential | `TWILIO_MAX_RETRIES` |
| Monitoring window | 30 days | `MONITORING_WINDOW_DAYS` |
| Accuracy alert threshold | 0.85 | `ACCURACY_ALERT_THRESHOLD` |
| Drift score threshold | 0.3 | `DRIFT_SCORE_THRESHOLD` |
| Bias p-value threshold | 0.05 | `BIAS_P_VALUE_THRESHOLD` |
| Evaluation seed | 42 | `evaluation/common.py` |

## Input formats

| Agent | Expected input |
|---|---|
| 1 | audio file .wav/.mp3/.m4a/.ogg/.webm/.flac (multipart `file`) |
| 1 (structured) | JSON `StructuredIntakeRequest` (`json_examples/structured_request.json`) |
| 2 | complaint text + optional vitals dict (F, /min, %, mmHg) |
| 3 | chat messages (system prompt with evidence, user message with statement + structured data) |
| 4 | raw model text; vitals + ACVPU for NEWS2 |
| 5 | severity, complaint, reasoning, NEWS2, session id -> n8n JSON event |
| 6 | JSON `{session_id, feedback, notes, reviewed_by}` |
| 7 | session rows in a 30-day window |
