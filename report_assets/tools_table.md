# Tools and methods (facts only)

| Category | Tool | Version | Purpose in this system | Facts relevant to the choice |
|---|---|---|---|---|
| Language | Python | 3.12.10 (local); 3.11-slim (Dockerfile) | All agents, API, evaluation | scikit-learn, pandas, SQLAlchemy, Whisper available; single language for backend and UI |
| API framework | FastAPI + Uvicorn | 0.115.6 / 0.32.1 | REST API, request validation, OpenAPI `/docs` | async; Pydantic integration; automatic OpenAPI schema |
| Validation / guardrail | Pydantic | 2.10.3 | Agent 4 `TriageResult` schema, request/response models | JSON schema validation errors returned as structured messages (used in the repair prompt) |
| Settings | pydantic-settings | 2.6.1 | `.env` / environment configuration | one typed `Settings` object |
| Speech-to-text | OpenAI Whisper `base.en` | openai-whisper 20250625 (torch 2.14.0) | Agent 1 transcription | runs locally on CPU (`fp16=False`); no audio leaves the server; 74M parameters |
| LLM | Groq API, `openai/gpt-oss-20b` | groq SDK 0.13.1 | Agent 3 reasoning | free tier (1,000 requests/day, 8,000 tokens/min observed in headers); JSON mode (`response_format=json_object`); temperature 0; `reasoning_effort=low` (37 vs 93 completion tokens than medium on a test prompt) |
| Retrieval | Custom TF-IDF + clinical synonym normaliser + Gaussian vitals kernel | in `retrieval_service.py` | Agent 2 | CPU only; every match explainable token by token; no embedding model download |
| Clinical score | NHS NEWS2 (RCP 2017) | `app/services/news2.py` | Agent 4 safety net | deterministic; NHS standard early-warning score; raise-only rule |
| Orchestration | n8n | 2.48.7 (npx) | Agent 5 workflow: webhook -> secret check -> IF -> Twilio / mocked -> response | free self-hosted; visual workflow; Twilio node built in |
| Messaging | Twilio WhatsApp API | twilio SDK 9.3.7 | Agent 5 alerts (fallback path and n8n node) | WhatsApp sandbox free for testing; retries with exponential backoff |
| Database | SQLite via SQLAlchemy 2.0.36 (+ Alembic 1.14.0) | — | MIMIC knowledge base, sessions, feedback, alert log, drift metrics | single file shipped with the Space (Git LFS); Postgres supported via `DATABASE_URL` |
| UI | Gradio | 5.0.0 local / 5.9.1 Space (`sdk_version`) | Patient Kiosk, Clinician Intake, Doctor Portal, Evaluation, Admin tabs | Hugging Face Space native SDK; microphone component |
| Statistics | SciPy | 1.16.3 | Agent 7 tests (KS, chi-squared, Jensen-Shannon), McNemar exact test | — |
| ML baselines | scikit-learn | 1.7.2 | S2a Logistic Regression, S2b Random Forest, TF-IDF, splits, CV, metrics | class_weight='balanced'; seed 42 |
| Data | pandas / NumPy / openpyxl | 2.3.3 / 2.3.5 / 3.1.5 | Loading MIMIC CSVs and the KTAS XLSX | — |
| Figures | matplotlib | 3.10.7 | 300 dpi evaluation figures | colour-blind-safe categorical palette |
| Testing | pytest + httpx (FastAPI TestClient) | 8.3.4 / 0.28.1 | unit + integration tests | Whisper, Groq, Twilio and n8n mocked; no network needed |
| Screenshots | Playwright (Chromium) | see environment.md | automated UI screenshots | headless, reproducible |
| Hosting | Hugging Face Spaces | ZeroGPU (`zero-a10g`) hardware | public demo | free; Space cannot reach a local n8n |
| Audio tooling | imageio-ffmpeg | 0.8.1 (ffmpeg 9.0.2) | ffmpeg binary for Whisper locally | no admin install needed |

## Methods compared in the evaluation

| ID | Method | Inputs |
|---|---|---|
| S0 | Majority class | none |
| S1 | Similarity-weighted k-NN vote over Agent 2 retrieval | complaint + vitals |
| S2a | Logistic Regression | TF-IDF complaint + scaled vitals + pain + sex (+ age, AVPU, arrival, injury for KTAS) |
| S2b | Random Forest | same as S2a |
| S3 | LLM without historical evidence (Agents 3+4) | statement + structured data |
| S4 | Full system (Agents 2+3+4, weak-evidence flag, repair loop, NEWS2) | statement + structured data + evidence |
| S4-noNEWS2 | S4 severity before the NEWS2 safety net | same calls as S4 |
| S4-promptv1 | S4 with the previous release prompt | MIMIC test only |
| H | Triage nurse (KTAS_RN) | KTAS only |
