# NHS Triage Assistant — Setup Instructions

## 0. Prerequisites
- Docker and Docker Compose installed.
- The MIMIC-IV-ED demo CSVs (`edstays.csv`, `triage.csv`, `diagnosis.csv`,
  `medrecon.csv`, `pyxis.csv`, `vitalsign.csv`) downloaded locally.
- A Groq API key.

## 1. Configure environment variables

```bash
cp .env.example .env
# Edit .env and set at minimum:
#   GROQ_API_KEY=your_real_key
#   POSTGRES_PASSWORD=a_real_password   (also used by docker-compose.yml)
```

## 2. Start PostgreSQL and the FastAPI backend

```bash
docker compose up -d db
# Wait for the db healthcheck to pass before continuing:
docker compose ps
```

Start only `db` first (not `api` yet) because the schema needs to exist
before the API container's health check will pass.

## 3. Initialize Alembic (one-time setup)

Run this locally (not inside the container) so the generated `alembic/`
folder is written to your project directory:

```bash
pip install alembic
alembic init alembic
```

Then edit `alembic.ini`:

```ini
sqlalchemy.url = postgresql+psycopg2://nhs_user:change_me@localhost:5432/nhs_triage
```
(use the same credentials as your `.env` file; `localhost` because you're
running Alembic from the host machine against the container's published port)

Edit `alembic/env.py` to point at the app's metadata, so autogenerate can
detect the models. Add near the top:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import Base
target_metadata = Base.metadata
```

## 4. Generate and run the first migration

```bash
alembic revision --autogenerate -m "Initial schema: ed_stays, triage, diagnoses, med_reconciliations, pyxis_medications, vital_signs, triage_sessions"
alembic upgrade head
```

Verify the tables were created:

```bash
docker compose exec db psql -U nhs_user -d nhs_triage -c "\dt"
```

## 5. Import the MIMIC-IV-ED CSV data

Run the import script locally (it uses the same `DATABASE_URL` from your
`.env`, pointed at `localhost:5432` since Postgres's port is published):

```bash
pip install -r requirements.txt
python -m scripts.import_mimic_csv --data-dir /path/to/your/mimic-iv-ed-csvs
```

You should see log lines like:
```
EDStay import complete: 5000 loaded, 0 skipped (missing stay_id).
Triage import complete: 5000 inserted, 0 skipped (orphan stay_id), 0 with unmapped acuity.
...
Import finished successfully.
```

## 6. Start the API container

```bash
docker compose up -d api
docker compose logs -f api
```

Confirm it's healthy:

```bash
curl http://localhost:8000/health
# {"status": "ok", "environment": "production"}
```

## 7. Run the Gradio frontend

The frontend is a separate, lightweight client and is not included in
`docker-compose.yml` (it doesn't need Postgres or GPU/CPU-heavy Whisper —
it just talks HTTP to the API). Run it locally or in its own container:

```bash
cd frontend
pip install -r requirements.txt
export BACKEND_URL=http://localhost:8000
export DOCTOR_PORTAL_PIN=1234   # change this for anything beyond local testing
python app.py
```

Open the printed local URL (default `http://localhost:7860`). Use the
Patient Kiosk tab to record a test symptom description, and the Doctor
Portal tab (PIN-gated) to see the full transcript, structured JSON, and
the historical evidence cases behind the severity rating.

## 8. End-to-end smoke test (optional, via curl)

```bash
curl -X POST http://localhost:8000/api/v1/process-triage \
  -F "file=@/path/to/test_recording.wav"
```

## Everyday commands

```bash
docker compose up -d          # start db + api
docker compose down           # stop everything
docker compose down -v        # stop and wipe the Postgres volume (destructive)
docker compose logs -f api    # tail API logs
alembic revision --autogenerate -m "description"   # after changing models.py
alembic upgrade head                                # apply new migrations
```
