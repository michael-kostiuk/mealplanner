import threading
from datetime import date, datetime, timedelta

import pytest

from app import models
from app.config import get_settings
from app.demo import database as demo_database
from app.demo import lifecycle
from app.demo.database import get_demo_session_factory
from app.demo.lifecycle import demo_status, ensure_demo_fresh, rebuild_demo_db
from app.demo.seed import load_seed


@pytest.fixture
def demo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "demo.sqlite"))
    get_settings.cache_clear()
    demo_database.dispose_demo_engine()
    yield
    demo_database.dispose_demo_engine()
    monkeypatch.undo()
    get_settings.cache_clear()


def _monday() -> datetime:
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


def test_rebuild_loads_seed_and_current_week_plan(demo_env):
    rebuild_demo_db()
    with get_demo_session_factory()() as db:
        assert db.query(models.Recipe).count() == 3
        assert db.query(models.User).count() == 1
        plans = db.query(models.MealPlan).all()
        assert len(plans) == 1
        assert plans[0].start_date == _monday()
        assert len(plans[0].entries) > 0
        lists = db.query(models.ShoppingList).all()
        assert len(lists) == 1
        assert len(lists[0].items) > 0
    assert demo_status()["current_week_plan"] is True
    assert demo_status()["last_reset"] is not None


def test_unknown_seed_key_rejected(demo_env):
    rebuild_demo_db()
    with get_demo_session_factory()() as db, pytest.raises(ValueError):
        load_seed(db, {"version": 1, "ingredients": [{"key": "1", "bogus": 1}], "recipes": []})


def test_stale_reset_triggers_rebuild(demo_env):
    rebuild_demo_db()
    with get_demo_session_factory()() as db:
        db.add(models.Recipe(name="Extra", servings=1, instructions="x"))
        db.commit()
        assert db.query(models.Recipe).count() == 4
    lifecycle._last_reset -= 8 * 86400
    ensure_demo_fresh()
    with get_demo_session_factory()() as db:
        assert db.query(models.Recipe).count() == 3


def _delete_plans():
    with get_demo_session_factory()() as db:
        db.query(models.MealPlan).delete()
        db.commit()
    lifecycle._cached_week = None


def test_new_week_generates_plan(demo_env):
    rebuild_demo_db()
    _delete_plans()
    ensure_demo_fresh()
    with get_demo_session_factory()() as db:
        assert db.query(models.MealPlan).count() == 1


def test_concurrent_freshness_generates_one_plan(demo_env):
    rebuild_demo_db()
    _delete_plans()
    barrier = threading.Barrier(8)
    errors = []

    def worker():
        try:
            barrier.wait()
            ensure_demo_fresh()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with get_demo_session_factory()() as db:
        assert db.query(models.MealPlan).count() == 1


def test_rebuild_keeps_in_flight_session_valid(demo_env):
    rebuild_demo_db()
    old = get_demo_session_factory()()
    try:
        assert old.query(models.Recipe).count() == 3
        old.add(models.Recipe(name="Extra", servings=1, instructions="x"))
        old.commit()
        assert old.query(models.Recipe).count() == 4

        rebuild_demo_db()

        assert old.query(models.Recipe).count() == 4  # old file untouched and still readable
        with get_demo_session_factory()() as fresh:
            assert fresh.query(models.Recipe).count() == 3
    finally:
        old.close()


def test_real_seed_has_27_recipes_and_varied_week(demo_env, monkeypatch):
    monkeypatch.setenv("DEMO_SEED_PATH", "app/demo/seed.json")
    get_settings.cache_clear()
    rebuild_demo_db()
    with get_demo_session_factory()() as db:
        assert db.query(models.Recipe).count() == 27
        plan = db.query(models.MealPlan).one()
        assert len({e.recipe_id for e in plan.entries if e.recipe_id}) >= 10
