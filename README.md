# AI-Powered Clinical Triage Assistant

An advanced clinical decision support system designed to assist healthcare professionals in Emergency Departments (ED). The application implements a Retrieval-Augmented Generation (RAG) pipeline combined with Large Language Models (LLMs) to analyze patient vitals, clinical histories, and audio transcripts, delivering evidence-based triage priority recommendations (ESI Levels 1-5).

## System Architecture

The project follows a decoupled, production-grade microservices architecture:

* **Frontend:** Gradio - Provides a responsive, clinician-facing dashboard for multi-modal data input and real-time inference visualization.
* **Backend:** FastAPI - Manages asynchronous routing, request validation, business logic orchestration, and RAG execution.
* **Database & Storage:** SQLite with SQLAlchemy ORM - A self-contained, file-based relational database storing structured anonymized clinical histories for rapid vector-like retrieval.
* **Inference Engine:** Groq API (`openai/gpt-oss-20b`) - Executes low-latency, high-throughput natural language generation and clinical reasoning.
* **Speech-to-Text Pipeline:** OpenAI Whisper (`base.en`) - Transcribes clinician-patient voice interactions into structured textual symptom profiles.

## Core Components & Data Flow

1. **Multi-Modal Data Ingestion:** 
   Clinicians can input patient parameters via structured forms (vital signs, chief complaints, pain scales) or stream audio descriptions. Audio files are processed locally via Whisper to extract symptom text.
   
2. **Retrieval-Augmented Generation (RAG):**
   To mitigate LLM hallucinations and ground clinical outputs in empirical data, the system queries historical admissions from the MIMIC-IV-ED dataset. Based on the patient's presenting condition, the module retrieves the $k$-most similar historical cases ($k=5$).
   
3. **Clinical Synthesis & Decision Support:**
   The current patient profile, along with the retrieved historical precedents, is formatted into a structured prompt and sent to the LLM via Groq. The system outputs a standardized triage score accompanied by an explainable clinical rationale.

## Dataset Structure

The system utilizes a localized relational subset of the **MIMIC-IV-ED** (Medical Information Mart for Intensive Care) database, encompassing:
* `edstays.csv`: Emergency department admission and discharge metrics.
* `triage.csv`: Initial vital signs, acuity scores, and chief complaints.
* `diagnosis.csv`: Coded clinical diagnoses.
* `vitalsign.csv`: Time-series physiological measurements.
* `pyxis.csv` & medication records: Pharmacological intervention history.

## Project Structure

```text
nhs-clinical-triage/
├── alembic/                # Database migration scripts
├── app/
│   ├── api/v1/             # FastAPI routers and endpoints
│   ├── core/               # Configuration and security settings
│   ├── db/                 # Database session and base definitions
│   ├── models/             # SQLAlchemy ORM models (MIMIC schema)
│   ├── schemas/            # Pydantic validation schemas
│   └── services/           # Business logic (LLM, RAG, Audio processing)
├── data/                   # Local CSV data sources for MIMIC-IV-ED subset
├── scripts/                # Data import and initialization utilities
├── app.py                  # Main application entry point
├── Dockerfile              # Containerization configuration
├── docker-compose.yml      # Multi-service orchestration definition
└── requirements.txt        # Python dependencies
```

## Local Installation & Setup

1. Clone the repository:
   git clone https://github.com/UmitKayaardi/nhs-clinical-triage.git
   cd nhs-clinical-triage

2. Install dependencies:
   pip install -r requirements.txt

3. Configure environment variables:
   Create a .env file in the root directory and set your Groq API key:
   DATABASE_URL=sqlite:///./triage_data.db
   GROQ_API_KEY=your_groq_api_key_here

4. Initialize the database and import sample clinical data:
   python setup_db.py
   python -m scripts.import_mimic_csv --data-dir data

5. Run the application:
   python app.py
