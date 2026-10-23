import json
import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from .. import models
from ..auth.deps import DEMO_USER_ID
from ..config import get_settings
from ..routers.shopping_lists import generate_shopping_list
from ..services.meal_plan_generator import MealPlanGenerator
from .database import dispose_demo_engine, get_demo_engine, get_demo_session_factory
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
    """Throw away the demo DB file and rebuild it from the seed."""
    global _last_reset
    with _lock:
        dispose_demo_engine()
        path = get_settings().demo_db_path
        # Remove the SQLite file and any journal/WAL leftovers
        db_file = Path(path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(db_file) + suffix).unlink(missing_ok=True)

        models.Base.metadata.create_all(get_demo_engine())
        with open(get_settings().demo_seed_path, encoding="utf-8") as f:
            seed = json.load(f)
        with get_demo_session_factory()() as db:
            load_seed(db, seed)
            ensure_current_week_plan(db)
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


def demo_status() -> dict:
    return {
        "last_reset": (
            datetime.fromtimestamp(_last_reset, tz=UTC).isoformat() if _last_reset else None
        ),
        "current_week_plan": _cached_week == _current_week(),
    }
