import logging

from fastapi import APIRouter, status
from sqlalchemy import text

from ..core.google_ai_client import get_ai_provider, get_google_ai_client
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


def _trim_detail(detail: str, limit: int = 200) -> str:
    return detail[:limit]


async def _check_database() -> tuple[bool, str | None]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except Exception as e:
        logger.error("Database health check failed: %s", e, exc_info=True)
        return False, _trim_detail(str(e))


async def _check_google_ai() -> tuple[bool, str | None]:
    try:
        client = get_google_ai_client()
    except ValueError as exc:
        return False, str(exc)

    ok, detail = await client.check_health()
    if detail:
        detail = _trim_detail(detail)
    return ok, detail


@router.get("/extended", status_code=status.HTTP_200_OK)
async def extended_healthcheck():
    """
    Extended healthcheck that verifies dependencies.
    Returns per-service status plus aggregate state.
    """
    db_ok, db_detail = await _check_database()
    dropbox_ok, dropbox_detail = await dropbox_service.check_health()
    google_ok, google_detail = await _check_google_ai()
    ai_provider = get_ai_provider()

    services = {
        "database": {"status": "ok" if db_ok else "error"},
        "dropbox": {"status": "ok" if dropbox_ok else "error"},
        "google_ai": {"status": "ok" if google_ok else "error", "provider": ai_provider},
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
