"""
FastAPI application entrypoint.

Initializes the app, configures CORS for external clients (e.g. a
separate React frontend or a Gradio kiosk client calling this API), and
registers the triage router.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.triage_routes import router as triage_router
from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    description="Evidence-grounded NHS triage support API: audio transcription, "
    "historical case retrieval, and structured LLM triage reporting.",
    version="1.0.0",
)

# Allow any origin by default so a separate React/Gradio frontend can
# call this API directly during development. Restrict CORS_ALLOW_ORIGINS
# to specific domains via the environment before deploying to production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(triage_router)


@app.get("/health", tags=["System"])
def health_check() -> dict:
    """Basic liveness check for load balancers / container orchestrators."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}
