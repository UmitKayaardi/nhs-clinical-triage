"""
Application configuration.

Centralizes all environment-dependent values (database URL, API keys,
model names, CORS origins) behind a single Settings object so no module
reads os.environ directly. Values are loaded from a local .env file in
development and from real environment variables in production/containers.
"""

from functools import lru_cache
from typing import List

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
    DATABASE_URL: str = Field(..., description="PostgreSQL connection string")

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
