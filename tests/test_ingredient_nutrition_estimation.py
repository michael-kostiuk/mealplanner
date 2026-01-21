import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app import models
from app.services.nutrition_estimator import NutritionEstimationError


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class MockNutrition:
    def __init__(self, calories: float, protein: float, carbs: float, fats: float):
        self.calories = calories
        self.protein = protein
        self.carbs = carbs
        self.fats = fats


class MockEstimator:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    async def estimate_nutrition(self, *args, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def add_ingredient(db_session, **kwargs):
    ingredient = models.Ingredient(**kwargs)
    db_session.add(ingredient)
    db_session.commit()
    return ingredient


def test_estimate_single_ingredient_updates_values(client, db_session):
    ingredient = add_ingredient(
        db_session,
        id=1,
        name="Carrot",
        category="vegetables",
        base_unit="g",
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
    )

    mock_estimator = MockEstimator(
        [MockNutrition(calories=41.0, protein=0.9, carbs=9.6, fats=0.2)]
    )

    with patch("app.routers.ingredients.get_nutrition_estimator", return_value=mock_estimator):
        response = client.post(f"/ingredients/{ingredient.id}/estimate-nutrition")

    assert response.status_code == 200
    data = response.json()
    assert data["calories"] == 41.0
    assert data["protein"] == 0.9
    assert data["carbs"] == 9.6
    assert data["fats"] == 0.2

    db_session.expire_all()
    refreshed = db_session.get(models.Ingredient, ingredient.id)
    assert refreshed.calories == 41.0
    assert refreshed.protein == 0.9
    assert refreshed.carbs == 9.6
    assert refreshed.fats == 0.2


def test_estimate_missing_bulk_skips_populated(client, db_session):
    missing = add_ingredient(
        db_session,
        id=1,
        name="Celery",
        category="vegetables",
        base_unit="g",
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
    )
    populated = add_ingredient(
        db_session,
        id=2,
        name="Olive Oil",
        category="fats",
        base_unit="g",
        calories=800,
        protein=0,
        carbs=0,
        fats=91,
    )

    mock_estimator = MockEstimator(
        [MockNutrition(calories=16.0, protein=0.7, carbs=3.0, fats=0.1)]
    )

    with patch("app.routers.ingredients.get_nutrition_estimator", return_value=mock_estimator):
        response = client.post("/ingredients/estimate-missing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["failed"] == []
    assert len(payload["updated"]) == 1
    assert payload["updated"][0]["id"] == missing.id

    db_session.expire_all()
    refreshed_missing = db_session.get(models.Ingredient, missing.id)
    refreshed_populated = db_session.get(models.Ingredient, populated.id)

    assert refreshed_missing.calories == 16.0
    assert refreshed_missing.protein == 0.7
    assert refreshed_missing.carbs == 3.0
    assert refreshed_missing.fats == 0.1

    assert refreshed_populated.calories == 800
    assert refreshed_populated.fats == 91


def test_estimate_missing_retries_on_rate_limit(client, db_session):
    ingredient = add_ingredient(
        db_session,
        id=1,
        name="Basil",
        category="herbs",
        base_unit="g",
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
    )

    mock_estimator = MockEstimator(
        [
            NutritionEstimationError("Rate limited", is_rate_limited=True),
            MockNutrition(calories=23.0, protein=3.2, carbs=2.7, fats=0.6),
        ]
    )

    with patch("app.routers.ingredients.get_nutrition_estimator", return_value=mock_estimator):
        response = client.post("/ingredients/estimate-missing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_count"] == 1
    assert payload["failed"] == []

    db_session.expire_all()
    refreshed = db_session.get(models.Ingredient, ingredient.id)
    assert refreshed.calories == 23.0
    assert refreshed.protein == 3.2
    assert refreshed.carbs == 2.7
    assert refreshed.fats == 0.6


def test_estimate_missing_returns_503_when_no_api_key(client, db_session):
    add_ingredient(
        db_session,
        id=1,
        name="Parsley",
        category="herbs",
        base_unit="g",
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
    )

    def raise_value_error():
        raise ValueError("GOOGLE_AI_API_KEY environment variable is not set")

    with patch("app.routers.ingredients.get_nutrition_estimator", side_effect=raise_value_error):
        response = client.post("/ingredients/estimate-missing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_count"] == 0
    assert payload["failed"]
    assert "not set" in payload["failed"][0]["reason"]
