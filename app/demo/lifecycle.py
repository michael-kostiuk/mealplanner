import json
import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from ..auth.deps import DEMO_USER_ID
from ..config import get_settings
from ..routers.shopping_lists import generate_shopping_list
from ..services.meal_plan_generator import MealPlanGenerator
from . import database
from .database import get_demo_session_factory
from .seed import load_seed

logger = logging.getLogger(__name__)

RESET_INTERVAL_SECONDS = 7 * 86400

# RLock: ensure_demo_fresh() holds it while calling rebuild_demo_db()
_lock = threading.RLock()
_last_reset: float = 0.0
_cached_week: tuple[int, int] | None = None


def _current_week() -> tuple[int, int]:
    iso = date.today().isocalendar()
    return (iso[0], iso[1])


def _this_monday() -> datetime:
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


def ensure_current_week_plan(db: Session) -> models.MealPlan:
    global _cached_week
    monday = _this_monday()
    plan = (
        db.query(models.MealPlan)
        .filter(models.MealPlan.user_id == DEMO_USER_ID, models.MealPlan.start_date == monday)
        .first()
    )
    if plan is None:
        plan = MealPlanGenerator(db).generate_meal_plan(
            start_date=monday,
            days=7,
            target_calories=2000,
            people_count=2,
            dietary_preferences=[],
            user_id=DEMO_USER_ID,
        )
        generate_shopping_list(plan, db)
        db.commit()
    _cached_week = _current_week()
    return plan


def rebuild_demo_db() -> None:
    """Build a fresh demo DB in a new file and swap it in; the old one is retired next time."""
    global _last_reset
    with _lock:
        if not database.has_generation():
            database.cleanup_leftover_files()
        gen = database.new_generation()
        models.Base.metadata.create_all(gen.engine)
        with open(get_settings().demo_seed_path, encoding="utf-8") as f:
            seed = json.load(f)
        with gen.factory() as db:
            load_seed(db, seed)
            ensure_current_week_plan(db)
        database.install_generation(gen)
        _last_reset = time.time()
        logger.info("Demo database rebuilt")


def ensure_demo_fresh() -> None:
    """Cheap per-request check: weekly full reset, and a new plan when the ISO week rolls."""
    if time.time() - _last_reset <= RESET_INTERVAL_SECONDS and _cached_week == _current_week():
        return
    with _lock:
        if time.time() - _last_reset > RESET_INTERVAL_SECONDS:
            rebuild_demo_db()
        elif _cached_week != _current_week():
            with get_demo_session_factory()() as db:
                ensure_current_week_plan(db)


def invalidate_current_week() -> None:
    """Force the next demo request to re-check (and if needed regenerate) the current plan."""
    global _cached_week
    _cached_week = None


def demo_status() -> dict:
    return {
        "last_reset": (
            datetime.fromtimestamp(_last_reset, tz=UTC).isoformat() if _last_reset else None
        ),
        "current_week_plan": _cached_week == _current_week(),
    }
