from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import models
from app.auth import rate_limit
from app.auth.session import SESSION_COOKIE, encode_session
from app.demo.database import get_demo_session_factory
from app.main import app

DEMO_NAMES = {"Oatmeal", "Chicken Plate", "Egg Scramble"}


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(rate_limit, "login_limiter", rate_limit.LoginLimiter())


def _recipe(name):
    return models.Recipe(
        name=name,
        servings=1,
        prep_time=1,
        cook_time=1,
        instructions="x",
        category="lunch",
        calories=500,
        protein=1.0,
        carbs=1.0,
        fats=1.0,
    )


@pytest.fixture
def client(owner_db):
    owner_db.add_all(
        [
            _recipe("PG One"),
            _recipe("PG Two"),
        ]
    )
    owner_db.commit()
    return TestClient(app)


def _names(response):
    assert response.status_code == 200
    return {r["name"] for r in response.json()}


def test_anonymous_sees_demo_recipes(client):
    assert _names(client.get("/recipes/")) == DEMO_NAMES


def test_owner_sees_postgres_recipes(client):
    assert client.post("/auth/login", json={"pin": "1234"}).status_code == 200
    assert _names(client.get("/recipes/")) == {"PG One", "PG Two"}


def test_cookie_for_missing_user_is_demo(client):
    client.cookies.set(SESSION_COOKIE, encode_session(999))
    assert _names(client.get("/recipes/")) == DEMO_NAMES


def _plan(user_id):
    return models.MealPlan(
        user_id=user_id,
        start_date=datetime(2026, 1, 5),
        end_date=datetime(2026, 1, 11),
        people_count=2,
        target_calories=2000,
        dietary_preferences=[],
    )


def _login_with_two_plans(client, owner_db):
    owner_db.add(models.User(id=2, email="other@example.com"))
    owner_db.commit()
    mine, theirs = _plan(1), _plan(2)
    owner_db.add_all([mine, theirs])
    owner_db.commit()
    assert client.post("/auth/login", json={"pin": "1234"}).status_code == 200
    return mine.id, theirs.id


def test_meal_plans_scoped_to_user(client, owner_db):
    mine, _ = _login_with_two_plans(client, owner_db)
    response = client.get("/meal-plans/")
    assert response.status_code == 200
    assert [p["id"] for p in response.json()] == [mine]


def test_other_users_plan_is_404(client, owner_db):
    _, theirs = _login_with_two_plans(client, owner_db)
    body = {
        "start_date": "2026-01-05T00:00:00",
        "end_date": "2026-01-11T00:00:00",
        "people_count": 2,
        "target_calories": 2000,
        "dietary_preferences": [],
        "entries": [],
    }
    assert client.get(f"/meal-plans/{theirs}").status_code == 404
    assert client.put(f"/meal-plans/{theirs}", json=body).status_code == 404
    assert client.delete(f"/meal-plans/{theirs}").status_code == 404
    assert client.get(f"/meal-plans/{theirs}/shopping-list").status_code == 404
    assert client.post("/meal-plans/auto-generate", params={"id": theirs}).status_code == 404


def test_demo_auto_generate_needs_no_user_id(client):
    response = client.post(
        "/meal-plans/auto-generate",
        params={
            "start_date": "2026-03-02T00:00:00",
            "days": 7,
            "target_calories": 2000,
            "people_count": 2,
        },
    )
    assert response.status_code == 200
    plan_id = response.json()["id"]
    with get_demo_session_factory()() as db:
        assert db.get(models.MealPlan, plan_id).user_id == 1
