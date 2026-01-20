import logging
import os
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, status
from sqlalchemy import text

from ..database import engine
from ..services.dropbox_service import dropbox_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("/", status_code=status.HTTP_200_OK)
async def basic_healthcheck():
    """Lightweight healthcheck for load balancers."""
    return {"status": "ok"}


def _resolve_gemini_models_url() -> str:
    """
    Build the Gemini models endpoint from the configured API URL (if provided),
    falling back to the public base URL.
    """
    default_base = "https://generativelanguage.googleapis.com"
    default_version = "v1beta"

    api_url = os.getenv("GEMINI_API_URL")
    if not api_url:
        return f"{default_base}/{default_version}/models"

    parsed = urlparse(api_url)
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else default_base
    path_parts = [part for part in parsed.path.split("/") if part]
    version = path_parts[0] if path_parts and path_parts[0].startswith("v1") else default_version
    return f"{base}/{version}/models"


def _trim_detail(detail: str, limit: int = 200) -> str:
    return detail[:limit]


async def _check_database() -> Tuple[bool, Optional[str]]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except Exception as e:
        logger.error("Database health check failed: %s", e, exc_info=True)
        return False, _trim_detail(str(e))


async def _check_google_ai() -> Tuple[bool, Optional[str]]:
    api_key = os.getenv("GOOGLE_AI_API_KEY")
    if not api_key:
        return False, "GOOGLE_AI_API_KEY not set"

    models_url = _resolve_gemini_models_url()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(models_url, params={"key": api_key, "pageSize": 1})

        if response.status_code == 200:
            return True, None

        preview = response.text[:200] if response.text else ""
        logger.warning("Google AI health check failed: %s %s", response.status_code, preview)
        return False, f"status_{response.status_code}: {preview}"
    except Exception as e:
        logger.error("Google AI health check error: %s", e, exc_info=True)
        return False, _trim_detail(str(e))


@router.get("/extended", status_code=status.HTTP_200_OK)
async def extended_healthcheck():
    """
    Extended healthcheck that verifies dependencies.
    Returns per-service status plus aggregate state.
    """
    db_ok, db_detail = await _check_database()
    dropbox_ok, dropbox_detail = await dropbox_service.check_health()
    google_ok, google_detail = await _check_google_ai()

    services = {
        "database": {"status": "ok" if db_ok else "error"},
        "dropbox": {"status": "ok" if dropbox_ok else "error"},
        "google_ai": {"status": "ok" if google_ok else "error"},
    }

    if db_detail:
        services["database"]["details"] = db_detail
    if dropbox_detail:
        services["dropbox"]["details"] = dropbox_detail
    if google_detail:
        services["google_ai"]["details"] = google_detail

    overall = "ok" if all((db_ok, dropbox_ok, google_ok)) else "degraded"

    return {
        "status": overall,
        "services": services,
    }
