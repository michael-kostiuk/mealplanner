import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import get_db
from app.main import app


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


def _recipe(**overrides):
    base = dict(
        name="Test Recipe",
        servings=1,
        prep_time=0,
        cook_time=0,
        instructions="Test",
        category="Test",
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
        breakfast_weight=0.0,
        lunch_weight=0.0,
        dinner_weight=0.0,
    )
    base.update(overrides)
    return models.Recipe(**base)


def test_shopping_list_aggregates_same_ingredient_same_unit(client, db_session):
    from datetime import datetime, timedelta

    user = models.User(id=1, email="test@test.com")
    db_session.add(user)

    ingredient = models.Ingredient(
        id=87,
        name="Mustard",
        category="condiments",
        base_unit="g",
        calories=0,
        protein=0,
        carbs=0,
        fats=0,
    )
    db_session.add(ingredient)

    r1 = _recipe(id=1, name="Recipe 1")
    r2 = _recipe(id=2, name="Recipe 2")
    db_session.add_all([r1, r2])
    db_session.commit()

    db_session.add_all(
        [
            models.RecipeIngredient(recipe_id=1, ingredient_id=87, quantity=1.0, unit="tsp"),
            models.RecipeIngredient(recipe_id=2, ingredient_id=87, quantity=1.0, unit="tsp"),
        ]
    )

    meal_plan = models.MealPlan(
        id=1,
        user_id=1,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=7),
        people_count=1,
        target_calories=0,
        dietary_preferences=[],
    )
    db_session.add(meal_plan)
    db_session.commit()

    db_session.add_all(
        [
            models.MealPlanEntry(
                meal_plan_id=1,
                recipe_id=1,
                date=datetime.utcnow(),
                meal_type="dinner",
                servings=1,
            ),
            models.MealPlanEntry(
                meal_plan_id=1,
                recipe_id=2,
                date=datetime.utcnow(),
                meal_type="dinner",
                servings=1,
            ),
        ]
    )
    db_session.commit()

    resp = client.get("/meal-plans/1/shopping-list")
    assert resp.status_code == 200

    db_session.expire_all()
    shopping_list = (
        db_session.query(models.ShoppingList).filter(models.ShoppingList.meal_plan_id == 1).first()
    )
    assert shopping_list is not None

    items = (
        db_session.query(models.ShoppingListItem)
        .filter(models.ShoppingListItem.shopping_list_id == shopping_list.id)
        .all()
    )
    assert len(items) == 1
    assert items[0].ingredient_id == 87
    assert items[0].unit == "tsp"
    assert items[0].quantity == 2

    recipes_resp = client.get(f"/shopping-lists/item/{items[0].id}/recipes")
    assert recipes_resp.status_code == 200
    recipe_ids = sorted([r["id"] for r in recipes_resp.json()])
    assert recipe_ids == [1, 2]
