"""
Application configuration.

Centralizes all environment-dependent values (database URL, API keys,
model names, CORS origins) behind a single Settings object so no module
reads os.environ directly. Values are loaded from a local .env file in
development and from real environment variables in production/containers.
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Strongly-typed application settings.
    All fields can be overridden via environment variables of the same
    name (case-insensitive), or via a `.env` file in the project root.
    """

    # --- General ---
    APP_NAME: str = "NHS Triage Assistant API"
    ENVIRONMENT: str = Field(default="development")  # development | staging | production
    DEBUG: bool = Field(default=False)

    # --- Database ---
    # Example: postgresql+psycopg2://user:password@localhost:5432/nhs_triage
    DATABASE_URL: str = Field(
        "sqlite:///./triage_data.db",
        description="SQLAlchemy URL; defaults to the bundled SQLite database used by the Space",
    )

    # --- Groq / LLM ---
    GROQ_API_KEY: str = Field(..., description="API key for the Groq API")
    # CRITICAL: This must remain "openai/gpt-oss-20b" per the project's
    # domain requirements. Do not silently swap to Llama/Mixtral.
    GROQ_MODEL_NAME: str = Field(default="openai/gpt-oss-20b")
    LLM_TEMPERATURE: float = Field(default=0.0)  # deterministic output, no creative guessing
    LLM_MAX_TOKENS: int = Field(default=1024)

    # --- Whisper / Audio ---
    WHISPER_MODEL_NAME: str = Field(default="base.en")
    AUDIO_TEMP_DIR: str = Field(default="/tmp/nhs_triage_audio")

    # --- Clinical search ---
    MIN_KEYWORD_LENGTH: int = Field(default=4)  # matches PoC rule: words > 4 chars
    MAX_SIMILAR_CASES: int = Field(default=5)

    # --- Agent 2: retrieval weights (exact complaint > diagnosis > vitals) ---
    RETRIEVAL_WEIGHT_COMPLAINT: float = Field(default=1.0)
    RETRIEVAL_WEIGHT_DIAGNOSIS: float = Field(default=0.7)
    RETRIEVAL_WEIGHT_VITALS: float = Field(default=0.5)
    RETRIEVAL_WEIGHT_MEDICATION: float = Field(default=0.3)

    # --- Agent 5: Twilio WhatsApp alerting ---
    # All four must be set for real messages to be sent. If any is
    # missing, or TWILIO_TEST_MODE is true, alerts are logged as "mocked"
    # instead of being dispatched (safe default for CI and the public demo).
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None)
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None)
    TWILIO_PHONE_NUMBER: Optional[str] = Field(default=None)     # WhatsApp-enabled sender, e.g. +14155238886
    DOCTOR_WHATSAPP_NUMBER: Optional[str] = Field(default=None)  # on-call device, e.g. +447700900123
    TWILIO_TEST_MODE: bool = Field(default=False)
    TWILIO_MAX_RETRIES: int = Field(default=3)
    TWILIO_RETRY_BACKOFF_SECONDS: float = Field(default=1.0)
    # Severities that trigger a WhatsApp alert (the workflow spec: High only).
    ALERT_ON_SEVERITIES: List[str] = Field(default=["High"])

    # --- Agents 6 & 7: monitoring, drift and bias ---
    MONITORING_WINDOW_DAYS: int = Field(default=30)
    ACCURACY_ALERT_THRESHOLD: float = Field(default=0.85)
    DRIFT_SCORE_THRESHOLD: float = Field(default=0.3)
    BIAS_P_VALUE_THRESHOLD: float = Field(default=0.05)
    # Below these sample sizes the statistics are too noisy to alert on.
    MIN_FEEDBACK_FOR_ACCURACY_ALERT: int = Field(default=10)
    MIN_SESSIONS_FOR_DRIFT: int = Field(default=10)

    # --- Admin protection & notifications ---
    # When set, /api/v1/feedback, /api/v1/alerts and /api/v1/admin/* require
    # the header `X-Admin-Key: <value>`. Leave unset only for local demos.
    ADMIN_API_KEY: Optional[str] = Field(default=None)
    ADMIN_EMAIL: Optional[str] = Field(default=None)
    SMTP_HOST: Optional[str] = Field(default=None)
    SMTP_PORT: int = Field(default=587)
    SMTP_USERNAME: Optional[str] = Field(default=None)
    SMTP_PASSWORD: Optional[str] = Field(default=None)
    SMTP_FROM: Optional[str] = Field(default=None)

    # --- CORS ---
    CORS_ALLOW_ORIGINS: List[str] = Field(default=["*"])

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    Using lru_cache ensures the .env file is parsed only once per process
    and the same Settings object is reused (and easily overridden in
    tests via dependency overrides / cache clearing).
    """
    return Settings()
