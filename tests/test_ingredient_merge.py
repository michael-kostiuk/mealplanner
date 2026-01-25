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


@pytest.fixture
def test_ingredients(db_session):
    ingredients = [
        models.Ingredient(
            id=1,
            name="сіль",
            category="Spices",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        ),
        models.Ingredient(
            id=2,
            name="salt",
            category="Spices",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        ),
        models.Ingredient(
            id=3,
            name="перець",
            category="Spices",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        ),
        models.Ingredient(
            id=4,
            name="black pepper",
            category="Spices",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        ),
        models.Ingredient(
            id=5,
            name="цибуля",
            category="Vegetables",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        ),
        models.Ingredient(
            id=6,
            name="onion",
            category="Vegetables",
            base_unit="g",
            calories=0,
            protein=0,
            carbs=0,
            fats=0,
        ),
    ]
    for ing in ingredients:
        db_session.add(ing)
    db_session.commit()
    return ingredients


@pytest.fixture
def test_recipes(db_session, test_ingredients):
    recipes = [
        models.Recipe(
            id=1,
            name="Recipe 1",
            servings=4,
            prep_time=10,
            cook_time=20,
            instructions="Test instructions",
            category="Test",
            calories=100,
            protein=10,
            carbs=20,
            fats=5,
            breakfast_weight=0.5,
            lunch_weight=0.5,
            dinner_weight=0.5,
        ),
        models.Recipe(
            id=2,
            name="Recipe 2",
            servings=2,
            prep_time=15,
            cook_time=30,
            instructions="Test instructions 2",
            category="Test",
            calories=150,
            protein=15,
            carbs=25,
            fats=10,
            breakfast_weight=0.3,
            lunch_weight=0.7,
            dinner_weight=0.3,
        ),
    ]
    for recipe in recipes:
        db_session.add(recipe)

    db_session.commit()

    recipe_ingredients = [
        models.RecipeIngredient(recipe_id=1, ingredient_id=1, quantity=1.0, unit="ч.л"),
        models.RecipeIngredient(recipe_id=1, ingredient_id=3, quantity=0.5, unit="ч.л"),
        models.RecipeIngredient(recipe_id=1, ingredient_id=5, quantity=2.0, unit="шт"),
        models.RecipeIngredient(recipe_id=2, ingredient_id=2, quantity=2.0, unit="ч.л"),
        models.RecipeIngredient(recipe_id=2, ingredient_id=4, quantity=1.0, unit="ч.л"),
        models.RecipeIngredient(recipe_id=2, ingredient_id=6, quantity=1.0, unit="шт"),
    ]
    for ri in recipe_ingredients:
        db_session.add(ri)

    db_session.commit()
    return recipes


@pytest.fixture
def test_shopping_lists(db_session, test_recipes, test_ingredients):
    from datetime import datetime, timedelta

    user = models.User(id=1, email="test@test.com", calorie_target=2000)
    db_session.add(user)
    db_session.commit()

    meal_plan = models.MealPlan(
        id=1,
        user_id=1,
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow() + timedelta(days=7),
        people_count=2,
        target_calories=2000,
        dietary_preferences=[],
    )
    db_session.add(meal_plan)
    db_session.commit()

    shopping_list = models.ShoppingList(id=1, meal_plan_id=1, status="active")
    db_session.add(shopping_list)
    db_session.commit()

    items = [
        models.ShoppingListItem(
            shopping_list_id=1, ingredient_id=1, quantity=1.0, unit="ч.л", category="Spices"
        ),
        models.ShoppingListItem(
            shopping_list_id=1, ingredient_id=2, quantity=2.0, unit="ч.л", category="Spices"
        ),
    ]
    for item in items:
        db_session.add(item)

    db_session.commit()
    return shopping_list


class TestIngredientMergeHappyPath:
    def test_merge_ingredients_success(
        self, client, db_session, test_ingredients, test_recipes, test_shopping_lists
    ):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200
        data = response.json()
        assert data["merged_count"] == 1
        assert "Successfully merged" in data["message"]

        db_session.expire_all()

        remaining_ingredient = (
            db_session.query(models.Ingredient).filter(models.Ingredient.id == 1).first()
        )
        assert remaining_ingredient is not None
        assert remaining_ingredient.name == "сіль"

        deleted_ingredient = (
            db_session.query(models.Ingredient).filter(models.Ingredient.id == 2).first()
        )
        assert deleted_ingredient is None

    def test_recipe_ingredients_updated_after_merge(
        self, client, db_session, test_ingredients, test_recipes
    ):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200

        db_session.expire_all()

        recipe_1_ings = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.recipe_id == 1)
            .all()
        )
        assert len(recipe_1_ings) == 3

        recipe_2_ings = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.recipe_id == 2)
            .all()
        )
        assert len(recipe_2_ings) == 3

        all_ings = db_session.query(models.RecipeIngredient).all()
        for ri in all_ings:
            assert ri.ingredient_id == 1 or ri.ingredient_id in [3, 4, 5, 6]
            assert ri.ingredient_id != 2

    def test_shopping_list_items_updated_after_merge(
        self, client, db_session, test_ingredients, test_recipes, test_shopping_lists
    ):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200

        db_session.expire_all()

        shopping_items = db_session.query(models.ShoppingListItem).all()
        assert len(shopping_items) == 2

        for item in shopping_items:
            assert item.ingredient_id == 1
            assert item.ingredient_id != 2


class TestIngredientMergeEdgeCases:
    def test_merge_nonexistent_keep_ingredient(self, client, db_session, test_ingredients):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 999}, json=[1])

        assert response.status_code == 404
        assert "Keep ingredient not found" in response.json()["detail"]

    def test_merge_nonexistent_merge_ingredient(self, client, db_session, test_ingredients):
        response = client.post(
            "/ingredients/merge", params={"keep_ingredient_id": 1}, json=[1, 999]
        )

        assert response.status_code == 404
        assert "One or more merge ingredients not found" in response.json()["detail"]

    def test_keep_ingredient_in_merge_list(self, client, db_session, test_ingredients):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[1, 2])

        assert response.status_code == 400
        assert "Keep ingredient cannot be in the merge list" in response.json()["detail"]

    def test_merge_single_ingredient(self, client, db_session, test_ingredients):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200
        assert response.json()["merged_count"] == 1

    def test_merge_multiple_ingredients(self, client, db_session, test_ingredients):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 3}, json=[4])

        assert response.status_code == 200
        assert response.json()["merged_count"] == 1

        deleted = db_session.query(models.Ingredient).filter(models.Ingredient.id == 4).first()
        assert deleted is None

        remaining = db_session.query(models.Ingredient).filter(models.Ingredient.id == 3).first()
        assert remaining is not None


class TestIngredientMergeNoSideEffects:
    def test_unaffected_recipes_unchanged(self, client, db_session, test_ingredients, test_recipes):
        original_recipe_2_count = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.recipe_id == 2)
            .count()
        )

        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200

        db_session.expire_all()

        current_recipe_2_count = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.recipe_id == 2)
            .count()
        )
        assert current_recipe_2_count == original_recipe_2_count

    def test_unaffected_ingredients_unchanged(self, client, db_session, test_ingredients):
        original_count = db_session.query(models.Ingredient).count()

        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200

        current_count = db_session.query(models.Ingredient).count()
        assert current_count == original_count - 1

        ingredient_3 = db_session.query(models.Ingredient).filter(models.Ingredient.id == 3).first()
        assert ingredient_3 is not None
        assert ingredient_3.name == "перець"

    def test_do_merge_function_recipes_updated(self, db_session, test_ingredients, test_recipes):
        db_session.query(models.RecipeIngredient).filter(
            models.RecipeIngredient.ingredient_id == 2
        ).update({models.RecipeIngredient.ingredient_id: 1}, synchronize_session=False)

        db_session.commit()

        recipe_2_ings = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.recipe_id == 2)
            .all()
        )

        for ri in recipe_2_ings:
            assert ri.ingredient_id != 2

    def test_merge_with_empty_merge_list(self, client, db_session, test_ingredients):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[])

        assert response.status_code == 200
        assert response.json()["merged_count"] == 0

        ingredient_1 = db_session.query(models.Ingredient).filter(models.Ingredient.id == 1).first()
        assert ingredient_1 is not None


class TestIngredientMergeDataIntegrity:
    def test_recipe_ingredient_relationships_preserved(
        self, client, db_session, test_ingredients, test_recipes
    ):
        original_ri = (
            db_session.query(models.RecipeIngredient)
            .filter(
                models.RecipeIngredient.recipe_id == 2, models.RecipeIngredient.ingredient_id == 2
            )
            .first()
        )

        assert original_ri is not None
        original_quantity = original_ri.quantity
        original_unit = original_ri.unit

        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200

        db_session.expire_all()

        updated_ri = (
            db_session.query(models.RecipeIngredient)
            .filter(
                models.RecipeIngredient.recipe_id == 2, models.RecipeIngredient.ingredient_id == 1
            )
            .first()
        )

        assert updated_ri is not None
        assert updated_ri.quantity == original_quantity
        assert updated_ri.unit == original_unit

    def test_merged_ingredient_fully_removed(
        self, client, db_session, test_ingredients, test_recipes
    ):
        response = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])

        assert response.status_code == 200

        deleted_ingredient = (
            db_session.query(models.Ingredient).filter(models.Ingredient.id == 2).first()
        )
        assert deleted_ingredient is None

        deleted_recipe_ing = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.ingredient_id == 2)
            .first()
        )
        assert deleted_recipe_ing is None

    def test_multiple_merges_affect_correct_ingredients(
        self, client, db_session, test_ingredients, test_recipes, test_shopping_lists
    ):
        response1 = client.post("/ingredients/merge", params={"keep_ingredient_id": 1}, json=[2])
        assert response1.status_code == 200

        response2 = client.post("/ingredients/merge", params={"keep_ingredient_id": 3}, json=[4])
        assert response2.status_code == 200

        db_session.expire_all()

        remaining_ingredients = db_session.query(models.Ingredient).all()
        remaining_ids = [ing.id for ing in remaining_ingredients]

        assert 1 in remaining_ids
        assert 3 in remaining_ids
        assert 2 not in remaining_ids
        assert 4 not in remaining_ids

        recipe_1_ings = (
            db_session.query(models.RecipeIngredient)
            .filter(models.RecipeIngredient.recipe_id == 1)
            .all()
        )
        recipe_1_ids = [ri.ingredient_id for ri in recipe_1_ings]

        assert 2 not in recipe_1_ids
        assert 4 not in recipe_1_ids
