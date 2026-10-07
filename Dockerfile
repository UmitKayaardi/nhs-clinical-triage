# --- Base image ---
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr,
# which keeps container logs flowing in real time.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- System dependencies ---
# ffmpeg: required by openai-whisper to decode audio formats (mp3, m4a, etc.)
# build-essential + libpq-dev: required to build psycopg2 from source if the
#   binary wheel is unavailable for the target platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies ---
# Copied and installed before the rest of the source so Docker can cache
# this layer and skip reinstalling on every code change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Application source ---
COPY app ./app
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini .

# Directory used by audio_service for temporary uploaded recordings.
RUN mkdir -p /tmp/nhs_triage_audio

# Run as a non-root user for defense-in-depth.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app /tmp/nhs_triage_audio
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# --workers 1 is deliberate: the Whisper model is loaded once as an
# in-process singleton (see audio_service.py). Running multiple Uvicorn
# workers would load a separate copy of the model into each worker's
# memory. Scale horizontally with multiple containers behind a load
# balancer instead of increasing --workers here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
