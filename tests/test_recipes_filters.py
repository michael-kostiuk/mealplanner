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
def test_recipes(db_session):
    """Create a variety of recipes for testing filters."""
    recipes = [
        models.Recipe(
            id=1,
            name="Chicken Salad",
            servings=2,
            prep_time=15,
            cook_time=0,
            instructions="Mix chicken with vegetables",
            category="Salad",
            calories=350,
            protein=30.0,
            carbs=10.0,
            fats=20.0,
        ),
        models.Recipe(
            id=2,
            name="Beef Stew",
            servings=4,
            prep_time=30,
            cook_time=120,
            instructions="Slow cook beef with vegetables",
            category="Main",
            calories=550,
            protein=40.0,
            carbs=30.0,
            fats=25.0,
        ),
        models.Recipe(
            id=3,
            name="Vegetable Soup",
            servings=6,
            prep_time=20,
            cook_time=45,
            instructions="Boil vegetables in broth",
            category="Soup",
            calories=150,
            protein=5.0,
            carbs=25.0,
            fats=3.0,
        ),
        models.Recipe(
            id=4,
            name="Grilled Chicken",
            servings=2,
            prep_time=10,
            cook_time=25,
            instructions="Grill chicken with herbs",
            category="Main",
            calories=400,
            protein=45.0,
            carbs=5.0,
            fats=22.0,
        ),
        models.Recipe(
            id=5,
            name="Caesar Salad",
            servings=2,
            prep_time=10,
            cook_time=0,
            instructions="Toss romaine with caesar dressing",
            category="Salad",
            calories=250,
            protein=8.0,
            carbs=15.0,
            fats=18.0,
        ),
        models.Recipe(
            id=6,
            name="Low Cal Snack",
            servings=1,
            prep_time=5,
            cook_time=0,
            instructions="Quick healthy snack",
            category="Snack",
            calories=100,
            protein=2.0,
            carbs=20.0,
            fats=1.0,
        ),
    ]
    for recipe in recipes:
        db_session.add(recipe)
    db_session.commit()
    return recipes


class TestRecipeNameFilter:
    """Tests for name filter (case-insensitive partial match)."""

    def test_filter_by_name_exact_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"name": "Chicken Salad"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Chicken Salad"

    def test_filter_by_name_partial_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"name": "Chicken"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Chicken Salad" in names
        assert "Grilled Chicken" in names

    def test_filter_by_name_case_insensitive(self, client, test_recipes):
        response = client.get("/recipes/", params={"name": "chicken"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Chicken Salad" in names
        assert "Grilled Chicken" in names

    def test_filter_by_name_no_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"name": "Pizza"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestRecipeCategoryFilter:
    """Tests for category filter (exact match)."""

    def test_filter_by_category_single_result(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Soup"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Vegetable Soup"
        assert data[0]["category"] == "Soup"

    def test_filter_by_category_multiple_results(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Main"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Beef Stew" in names
        assert "Grilled Chicken" in names

    def test_filter_by_category_salad(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Salad"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Chicken Salad" in names
        assert "Caesar Salad" in names

    def test_filter_by_category_no_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Dessert"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_filter_by_category_case_sensitive(self, client, test_recipes):
        """Category filter is case-sensitive (exact match)."""
        response = client.get("/recipes/", params={"category": "main"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestRecipePrepTimeFilter:
    """Tests for max_prep_time filter."""

    def test_filter_by_max_prep_time_includes_boundary(self, client, test_recipes):
        response = client.get("/recipes/", params={"max_prep_time": 10})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        names = [r["name"] for r in data]
        assert "Grilled Chicken" in names
        assert "Caesar Salad" in names
        assert "Low Cal Snack" in names
        for recipe in data:
            assert recipe["prep_time"] <= 10

    def test_filter_by_max_prep_time_15(self, client, test_recipes):
        response = client.get("/recipes/", params={"max_prep_time": 15})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 4
        for recipe in data:
            assert recipe["prep_time"] <= 15

    def test_filter_by_max_prep_time_all(self, client, test_recipes):
        response = client.get("/recipes/", params={"max_prep_time": 100})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 6

    def test_filter_by_max_prep_time_none_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"max_prep_time": 1})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestRecipeCaloriesFilter:
    """Tests for min_calories and max_calories filters."""

    def test_filter_by_min_calories(self, client, test_recipes):
        response = client.get("/recipes/", params={"min_calories": 400})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Beef Stew" in names  # 550 calories
        assert "Grilled Chicken" in names  # 400 calories
        assert "Chicken Salad" not in names  # 350 calories - below filter
        for recipe in data:
            assert recipe["calories"] >= 400

    def test_filter_by_max_calories(self, client, test_recipes):
        response = client.get("/recipes/", params={"max_calories": 200})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Vegetable Soup" in names
        assert "Low Cal Snack" in names
        for recipe in data:
            assert recipe["calories"] <= 200

    def test_filter_by_calories_range(self, client, test_recipes):
        response = client.get("/recipes/", params={"min_calories": 200, "max_calories": 400})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        names = [r["name"] for r in data]
        assert "Chicken Salad" in names
        assert "Grilled Chicken" in names
        assert "Caesar Salad" in names
        for recipe in data:
            assert 200 <= recipe["calories"] <= 400

    def test_filter_by_min_calories_boundary(self, client, test_recipes):
        response = client.get("/recipes/", params={"min_calories": 350})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        for recipe in data:
            assert recipe["calories"] >= 350

    def test_filter_by_max_calories_boundary(self, client, test_recipes):
        response = client.get("/recipes/", params={"max_calories": 350})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 4
        for recipe in data:
            assert recipe["calories"] <= 350

    def test_filter_by_calories_no_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"min_calories": 600, "max_calories": 700})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestRecipeCombinedFilters:
    """Tests for combining multiple filters."""

    def test_filter_by_category_and_name(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Salad", "name": "Chicken"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Chicken Salad"

    def test_filter_by_category_and_max_prep_time(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Main", "max_prep_time": 15})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Grilled Chicken"

    def test_filter_by_category_and_calories_range(self, client, test_recipes):
        response = client.get(
            "/recipes/",
            params={"category": "Main", "min_calories": 300, "max_calories": 500},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Grilled Chicken"

    def test_filter_by_name_and_max_calories(self, client, test_recipes):
        response = client.get("/recipes/", params={"name": "Salad", "max_calories": 300})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Caesar Salad"

    def test_filter_by_all_params(self, client, test_recipes):
        response = client.get(
            "/recipes/",
            params={
                "name": "Chicken",
                "category": "Salad",
                "max_prep_time": 20,
                "min_calories": 300,
                "max_calories": 400,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Chicken Salad"

    def test_filter_combined_no_match(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Salad", "min_calories": 500})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestRecipePagination:
    """Tests for pagination with filters."""

    def test_pagination_skip(self, client, test_recipes):
        response = client.get("/recipes/", params={"skip": 2})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 4

    def test_pagination_limit(self, client, test_recipes):
        response = client.get("/recipes/", params={"limit": 3})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    def test_pagination_skip_and_limit(self, client, test_recipes):
        response = client.get("/recipes/", params={"skip": 2, "limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_pagination_with_filter(self, client, test_recipes):
        response = client.get("/recipes/", params={"category": "Main", "skip": 1, "limit": 1})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    def test_skip_beyond_results(self, client, test_recipes):
        response = client.get("/recipes/", params={"skip": 100})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestRecipeNoFilters:
    """Tests for listing recipes without filters."""

    def test_list_all_recipes(self, client, test_recipes):
        response = client.get("/recipes/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 6

    def test_empty_database(self, client):
        response = client.get("/recipes/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


@pytest.fixture
def recipes_with_weights(db_session):
    """Create recipes with meal type weights for testing suggestions."""
    recipes = [
        models.Recipe(
            id=1,
            name="Oatmeal",
            servings=1,
            prep_time=10,
            cook_time=5,
            instructions="Cook oats with water",
            category="Breakfast",
            calories=300,
            protein=10.0,
            carbs=50.0,
            fats=5.0,
            breakfast_weight=0.9,
            lunch_weight=0.0,
            dinner_weight=0.0,
        ),
        models.Recipe(
            id=2,
            name="Scrambled Eggs",
            servings=2,
            prep_time=5,
            cook_time=10,
            instructions="Scramble eggs in pan",
            category="Breakfast",
            calories=250,
            protein=18.0,
            carbs=2.0,
            fats=18.0,
            breakfast_weight=0.8,
            lunch_weight=0.3,
            dinner_weight=0.1,
        ),
        models.Recipe(
            id=3,
            name="Grilled Chicken Salad",
            servings=2,
            prep_time=15,
            cook_time=20,
            instructions="Grill chicken and mix with salad",
            category="Main",
            calories=400,
            protein=35.0,
            carbs=15.0,
            fats=20.0,
            breakfast_weight=0.0,
            lunch_weight=0.9,
            dinner_weight=0.7,
        ),
        models.Recipe(
            id=4,
            name="Turkey Sandwich",
            servings=1,
            prep_time=10,
            cook_time=0,
            instructions="Assemble sandwich with turkey",
            category="Main",
            calories=450,
            protein=25.0,
            carbs=40.0,
            fats=18.0,
            breakfast_weight=0.1,
            lunch_weight=0.8,
            dinner_weight=0.2,
        ),
        models.Recipe(
            id=5,
            name="Beef Steak",
            servings=2,
            prep_time=10,
            cook_time=15,
            instructions="Pan sear steak",
            category="Main",
            calories=550,
            protein=45.0,
            carbs=0.0,
            fats=35.0,
            breakfast_weight=0.0,
            lunch_weight=0.4,
            dinner_weight=0.95,
        ),
        models.Recipe(
            id=6,
            name="Pasta Carbonara",
            servings=4,
            prep_time=15,
            cook_time=20,
            instructions="Cook pasta with egg sauce",
            category="Main",
            calories=600,
            protein=20.0,
            carbs=70.0,
            fats=25.0,
            breakfast_weight=0.0,
            lunch_weight=0.5,
            dinner_weight=0.85,
        ),
        models.Recipe(
            id=7,
            name="Pancakes",
            servings=2,
            prep_time=10,
            cook_time=15,
            instructions="Mix batter and cook on griddle",
            category="Breakfast",
            calories=350,
            protein=8.0,
            carbs=60.0,
            fats=10.0,
            breakfast_weight=0.7,
            lunch_weight=0.0,
            dinner_weight=0.0,
        ),
        models.Recipe(
            id=8,
            name="No Weight Recipe",
            servings=1,
            prep_time=5,
            cook_time=5,
            instructions="A recipe with no meal weights",
            category="Other",
            calories=100,
            protein=5.0,
            carbs=10.0,
            fats=5.0,
            breakfast_weight=0.0,
            lunch_weight=0.0,
            dinner_weight=0.0,
        ),
    ]
    for recipe in recipes:
        db_session.add(recipe)
    db_session.commit()
    return recipes


class TestRecipeSuggestions:
    """Tests for recipe suggestions endpoint."""

    def test_suggestions_breakfast_ordered_by_weight(self, client, recipes_with_weights):
        response = client.get("/recipes/suggestions", params={"meal_type": "breakfast"})
        assert response.status_code == 200
        data = response.json()
        # Should return recipes with breakfast_weight > 0, ordered by weight desc
        assert (
            len(data) == 4
        )  # Oatmeal(0.9), Scrambled Eggs(0.8), Pancakes(0.7), Turkey Sandwich(0.1)
        assert data[0]["name"] == "Oatmeal"  # highest weight 0.9
        assert data[1]["name"] == "Scrambled Eggs"  # weight 0.8
        assert data[2]["name"] == "Pancakes"  # weight 0.7
        assert data[3]["name"] == "Turkey Sandwich"  # weight 0.1

    def test_suggestions_lunch_ordered_by_weight(self, client, recipes_with_weights):
        response = client.get("/recipes/suggestions", params={"meal_type": "lunch"})
        assert response.status_code == 200
        data = response.json()
        # Should return recipes with lunch_weight > 0, ordered by weight desc
        assert len(data) == 5
        assert data[0]["name"] == "Grilled Chicken Salad"  # weight 0.9
        assert data[1]["name"] == "Turkey Sandwich"  # weight 0.8
        assert data[2]["name"] == "Pasta Carbonara"  # weight 0.5

    def test_suggestions_dinner_ordered_by_weight(self, client, recipes_with_weights):
        response = client.get("/recipes/suggestions", params={"meal_type": "dinner"})
        assert response.status_code == 200
        data = response.json()
        # Should return recipes with dinner_weight > 0, ordered by weight desc
        assert len(data) == 5
        assert data[0]["name"] == "Beef Steak"  # weight 0.95
        assert data[1]["name"] == "Pasta Carbonara"  # weight 0.85
        assert data[2]["name"] == "Grilled Chicken Salad"  # weight 0.7

    def test_suggestions_with_exclude_ids(self, client, recipes_with_weights):
        response = client.get(
            "/recipes/suggestions",
            params={"meal_type": "breakfast", "exclude_ids": [1, 2]},
        )
        assert response.status_code == 200
        data = response.json()
        # Should exclude Oatmeal(id=1) and Scrambled Eggs(id=2)
        assert len(data) == 2
        names = [r["name"] for r in data]
        assert "Oatmeal" not in names
        assert "Scrambled Eggs" not in names
        assert "Pancakes" in names
        assert "Turkey Sandwich" in names

    def test_suggestions_with_limit(self, client, recipes_with_weights):
        response = client.get("/recipes/suggestions", params={"meal_type": "lunch", "limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Should be top 2 by weight
        assert data[0]["name"] == "Grilled Chicken Salad"
        assert data[1]["name"] == "Turkey Sandwich"

    def test_suggestions_exclude_and_limit_combined(self, client, recipes_with_weights):
        response = client.get(
            "/recipes/suggestions",
            params={"meal_type": "dinner", "exclude_ids": [5], "limit": 2},
        )
        assert response.status_code == 200
        data = response.json()
        # Exclude Beef Steak (id=5, highest weight), return top 2
        assert len(data) == 2
        assert data[0]["name"] == "Pasta Carbonara"  # now highest
        assert data[1]["name"] == "Grilled Chicken Salad"

    def test_suggestions_invalid_meal_type(self, client, recipes_with_weights):
        response = client.get("/recipes/suggestions", params={"meal_type": "brunch"})
        assert response.status_code == 400
        assert "meal_type must be" in response.json()["detail"]

    def test_suggestions_missing_meal_type(self, client, recipes_with_weights):
        response = client.get("/recipes/suggestions")
        assert response.status_code == 422  # FastAPI validation error

    def test_suggestions_empty_when_no_weights(self, client, recipes_with_weights):
        # Exclude all recipes that have breakfast weight > 0
        response = client.get(
            "/recipes/suggestions",
            params={"meal_type": "breakfast", "exclude_ids": [1, 2, 4, 7]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_suggestions_empty_database(self, client):
        response = client.get("/recipes/suggestions", params={"meal_type": "breakfast"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_suggestions_excludes_zero_weight_recipes(self, client, recipes_with_weights):
        # "No Weight Recipe" (id=8) has all weights at 0, should never appear
        response = client.get("/recipes/suggestions", params={"meal_type": "breakfast"})
        assert response.status_code == 200
        data = response.json()
        names = [r["name"] for r in data]
        assert "No Weight Recipe" not in names

        response = client.get("/recipes/suggestions", params={"meal_type": "lunch"})
        data = response.json()
        names = [r["name"] for r in data]
        assert "No Weight Recipe" not in names

        response = client.get("/recipes/suggestions", params={"meal_type": "dinner"})
        data = response.json()
        names = [r["name"] for r in data]
        assert "No Weight Recipe" not in names

    def test_suggestions_default_limit(self, client, recipes_with_weights):
        # Default limit is 10, we have fewer recipes so should return all matching
        response = client.get("/recipes/suggestions", params={"meal_type": "lunch"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5  # All lunch recipes (< 10)
