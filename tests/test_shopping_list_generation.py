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


def _plan_with_entries(db_session, recipe_servings, entries):
    """entries: list of (day offset, meal_type, is_leftover) for one 400 g recipe."""
    from datetime import datetime, timedelta

    db_session.add(models.User(id=1, email="test@test.com"))
    db_session.add(
        models.Ingredient(
            id=5,
            name="Rice",
            category="grains",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        )
    )
    db_session.add(_recipe(id=1, name="Plov", servings=recipe_servings))
    db_session.commit()
    db_session.add(models.RecipeIngredient(recipe_id=1, ingredient_id=5, quantity=400, unit="g"))
    start = datetime(2026, 10, 5)
    db_session.add(
        models.MealPlan(
            id=1,
            user_id=1,
            start_date=start,
            end_date=start + timedelta(days=6),
            people_count=2,
            target_calories=0,
            dietary_preferences=[],
        )
    )
    db_session.commit()
    db_session.add_all(
        [
            models.MealPlanEntry(
                meal_plan_id=1,
                recipe_id=1,
                date=start + timedelta(days=day),
                meal_type=meal_type,
                servings=2,
                is_leftover=is_leftover,
            )
            for day, meal_type, is_leftover in entries
        ]
    )
    db_session.commit()


def _rice_quantity(client, db_session):
    assert client.get("/meal-plans/1/shopping-list").status_code == 200
    db_session.expire_all()
    items = db_session.query(models.ShoppingListItem).all()
    assert len(items) == 1
    return items[0].quantity


def test_shopping_list_leftovers_are_not_bought_twice(client, db_session):
    # 4-serving recipe for 2 people: cooked once, eaten again as leftovers next day
    _plan_with_entries(db_session, 4, [(0, "dinner", False), (1, "dinner", True)])
    assert _rice_quantity(client, db_session) == 400


def test_shopping_list_buys_full_batch_for_bigger_recipe(client, db_session):
    _plan_with_entries(db_session, 4, [(0, "dinner", False)])
    assert _rice_quantity(client, db_session) == 400


def test_shopping_list_buys_leftover_without_cooked_batch(client, db_session):
    # Cooking slot was re-rolled away; the leftover entry must still be bought
    _plan_with_entries(db_session, 4, [(1, "dinner", True)])
    assert _rice_quantity(client, db_session) == 400


def test_shopping_list_leftovers_beyond_batch_are_bought(client, db_session):
    # 4 servings cover the cooked meal + 1 leftover; the 2nd leftover needs a new batch
    _plan_with_entries(
        db_session, 4, [(0, "dinner", False), (1, "dinner", True), (2, "dinner", True)]
    )
    assert _rice_quantity(client, db_session) == 800


def _put_plan(client, recipe_ids):
    """Save plan 1 like the frontend does: all entries, without `is_leftover`."""
    resp = client.put(
        "/meal-plans/1",
        json={
            "start_date": "2026-10-05T00:00:00",
            "end_date": "2026-10-11T23:59:59",
            "people_count": 2,
            "target_calories": 0,
            "dietary_preferences": [],
            "entries": [
                {
                    "recipe_id": recipe_id,
                    "date": f"2026-10-0{5 + day}T00:00:00",
                    "meal_type": "dinner",
                    "servings": 2,
                }
                for day, recipe_id in enumerate(recipe_ids)
            ],
        },
    )
    assert resp.status_code == 200
    return [e["is_leftover"] for e in sorted(resp.json()["entries"], key=lambda e: e["date"])]


def test_saving_plan_without_flag_keeps_leftovers(client, db_session):
    _plan_with_entries(db_session, 4, [(0, "dinner", False), (1, "dinner", True)])

    assert _put_plan(client, [1, 1]) == [False, True]
    assert _rice_quantity(client, db_session) == 400


def test_saving_plan_with_changed_recipe_clears_leftover(client, db_session):
    _plan_with_entries(db_session, 4, [(0, "dinner", False), (1, "dinner", True)])
    db_session.add(_recipe(id=2, name="Other"))
    db_session.commit()

    assert _put_plan(client, [1, 2]) == [False, False]
