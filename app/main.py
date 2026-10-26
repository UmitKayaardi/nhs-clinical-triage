"""
FastAPI application entrypoint.

Initializes the app, configures CORS for external clients (e.g. a
separate React frontend or a Gradio kiosk client calling this API), and
registers the triage router.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.monitoring_routes import router as monitoring_router
from app.api.v1.triage_routes import router as triage_router
from app.core.config import get_settings
from app.db.schema import ensure_schema
from app.db.session import engine

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Bring file-based databases (the Space's triage_data.db) up to the
    # current schema without needing a separate migration step.
    ensure_schema(engine)
    if not settings.ADMIN_API_KEY:
        logger.warning("ADMIN_API_KEY is not set: feedback, alert and admin endpoints are unprotected.")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Evidence-grounded NHS triage support API: audio transcription, "
    "multi-table historical case retrieval, structured LLM triage reporting, "
    "WhatsApp alerting, and post-deployment accuracy, drift and bias monitoring.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak exception text (SQL, file paths, keys) to clients; the
    # traceback is in the server log.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})

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
app.include_router(monitoring_router)


@app.get("/health", tags=["System"])
def health_check() -> dict:
    """Basic liveness check for load balancers / container orchestrators."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}
