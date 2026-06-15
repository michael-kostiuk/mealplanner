from collections import Counter
from datetime import datetime, timedelta

import pytest

import app.services.meal_plan_generator as mpg
from app.models import MealPlan, MealPlanEntry, Recipe, User
from app.services.meal_plan_generator import MealPlanGenerator


# Helper to create a user
@pytest.fixture
def test_user(db_session):
    user = User(email="test@example.com", calorie_target=2000)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# Helper to create recipes
def create_recipes(db, count, prefix, calories, weights):
    recipes = []
    for i in range(count):
        r = Recipe(
            name=f"{prefix} {i}",
            servings=1,
            instructions=f"Instructions for {prefix} {i}",
            calories=calories,
            protein=10,
            carbs=10,
            fats=10,
            breakfast_weight=weights.get("breakfast", 0.0),
            lunch_weight=weights.get("lunch", 0.0),
            dinner_weight=weights.get("dinner", 0.0),
        )
        db.add(r)
        recipes.append(r)
    db.commit()
    return recipes


def test_generate_meal_plan_basic_success(db_session, test_user):
    """
    Test that a basic meal plan is generated successfully with the correct number of entries.
    """
    # Create sufficient recipes
    create_recipes(db_session, 5, "Breakfast", 400, {"breakfast": 1.0})
    create_recipes(db_session, 5, "Lunch", 600, {"lunch": 1.0})
    create_recipes(db_session, 5, "Dinner", 800, {"dinner": 1.0})

    generator = MealPlanGenerator(db_session)
    start_date = datetime.now()
    days = 7
    target_calories = 1800

    plan = generator.generate_meal_plan(
        start_date=start_date,
        days=days,
        target_calories=target_calories,
        people_count=1,
        dietary_preferences=[],
        user_id=test_user.id,
    )

    assert plan is not None
    assert plan.user_id == test_user.id
    assert plan.target_calories == target_calories

    # Check entries count: 7 days * 3 meals = 21 entries
    assert len(plan.entries) == 21

    # Check dates cover the range
    dates = sorted({entry.date.date() for entry in plan.entries})
    assert len(dates) == days
    assert dates[0] == start_date.date()
    assert dates[-1] == (start_date + timedelta(days=days - 1)).date()


def test_generate_meal_plan_calorie_matching(db_session, test_user):
    """
    Test that the generated meal plan attempts to match target calories.
    """
    # Create recipes with specific calorie counts
    # Target: 2000. Breakfast: 500, Lunch: 700, Dinner: 800
    create_recipes(db_session, 5, "B", 500, {"breakfast": 1.0})
    create_recipes(db_session, 5, "L", 700, {"lunch": 1.0})
    create_recipes(db_session, 5, "D", 800, {"dinner": 1.0})

    generator = MealPlanGenerator(db_session)
    target = 2000
    plan = generator.generate_meal_plan(
        start_date=datetime.now(),
        days=3,
        target_calories=target,
        people_count=1,
        dietary_preferences=[],
        user_id=test_user.id,
    )

    # Check daily totals
    # We expect roughly 2000 calories per day
    daily_calories = {}
    for entry in plan.entries:
        date_key = entry.date.date()
        if date_key not in daily_calories:
            daily_calories[date_key] = 0
        daily_calories[date_key] += entry.recipe.calories

    for date, total in daily_calories.items():
        # Allow some deviation (e.g. 10%)
        assert abs(total - target) < (target * 0.1), (
            f"Day {date} calories {total} too far from target {target}"
        )


def test_meal_type_weights_respected(db_session, test_user):
    """
    Test that breakfast meals have breakfast_weight > 0, etc.
    """
    # Create mixed recipes
    # Recipe 1: Only Breakfast
    r1 = Recipe(
        name="Only B",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=0.0,
        dinner_weight=0.0,
    )
    # Recipe 2: Only Lunch
    r2 = Recipe(
        name="Only L",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=0.0,
        lunch_weight=1.0,
        dinner_weight=0.0,
    )
    # Recipe 3: Only Dinner
    r3 = Recipe(
        name="Only D",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=0.0,
        lunch_weight=0.0,
        dinner_weight=1.0,
    )

    # Add copies to support 3 days (since usage limit is 2 per recipe)
    r1b = Recipe(
        name="Only B 2",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=0.0,
        dinner_weight=0.0,
    )
    r2b = Recipe(
        name="Only L 2",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=0.0,
        lunch_weight=1.0,
        dinner_weight=0.0,
    )
    r3b = Recipe(
        name="Only D 2",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=0.0,
        lunch_weight=0.0,
        dinner_weight=1.0,
    )

    db_session.add_all([r1, r2, r3, r1b, r2b, r3b])
    db_session.commit()

    generator = MealPlanGenerator(db_session)
    plan = generator.generate_meal_plan(
        start_date=datetime.now(),
        days=3,
        target_calories=1500,
        people_count=1,
        dietary_preferences=[],
        user_id=test_user.id,
    )

    for entry in plan.entries:
        recipe = entry.recipe
        if entry.meal_type == "breakfast":
            assert recipe.breakfast_weight > 0
            assert recipe.name.startswith("Only B")
        elif entry.meal_type == "lunch":
            assert recipe.lunch_weight > 0
            assert recipe.name.startswith("Only L")
        elif entry.meal_type == "dinner":
            assert recipe.dinner_weight > 0
            assert recipe.name.startswith("Only D")


def test_no_excessive_repetition(db_session, test_user):
    """
    Test that there are no 5 same meals in a week.
    Actually, current implementation limits to 2 same meals.
    We will test that it respects the limit (even if we force it to repeat).
    """
    # Create very few recipes
    # 1 Breakfast option
    create_recipes(db_session, 1, "B", 500, {"breakfast": 1.0})
    # 1 Lunch option
    create_recipes(db_session, 1, "L", 700, {"lunch": 1.0})
    # 1 Dinner option
    create_recipes(db_session, 1, "D", 800, {"dinner": 1.0})

    generator = MealPlanGenerator(db_session)

    # If we request 3 days, we need 3 breakfasts.
    # Since we only have 1 breakfast recipe, and the limit is 2 (from code reading),
    # the 3rd day generation might fail or behave unexpectedly if strict.
    # The code `_filter_and_sort_recipes` checks `used_recipes[r.id] < 2`.
    # So for the 3rd day, the recipe will be filtered out.
    # Then `_select_recipe` will filter `available_recipes` based on weight > 0.
    # If `available_recipes` is empty (because all filtered out by usage limit),
    # `_filter_and_sort_recipes` returns empty list.
    # Wait, `_generate_daily_meals` calls `_filter_and_sort_recipes` which does the filtering.
    # If it returns empty, then `_select_recipe` receives empty list?
    # No, `_select_recipe` takes `recipes` (all recipes?) NO.
    # `_generate_daily_meals` passes `breakfast_recipes` (which is filtered) to `_select_recipe`.
    # So `_select_recipe` receives empty list.
    # Then `available_recipes` inside `_select_recipe` will be empty.
    # Then `suitable_recipes` empty.
    # `selected` assignment will crash: `min() arg is an empty sequence` or `random.choices` on empty.

    # Let's see what happens. If it crashes, it's a finding.
    # But the requirement is "no 5 same meals in week".
    # If we provide 2 recipes, we can support 4 days.

    create_recipes(db_session, 1, "B2", 500, {"breakfast": 1.0})
    create_recipes(db_session, 1, "L2", 700, {"lunch": 1.0})
    create_recipes(db_session, 1, "D2", 800, {"dinner": 1.0})

    # Now we have 2 recipes per type. Max capacity = 4 days.
    # Let's request 4 days.

    days = 4
    plan = generator.generate_meal_plan(
        start_date=datetime.now(),
        days=days,
        target_calories=2000,
        people_count=1,
        dietary_preferences=[],
        user_id=test_user.id,
    )

    # Count occurrences
    recipe_counts = Counter()
    for entry in plan.entries:
        recipe_counts[entry.recipe_id] += 1

    for recipe_id, count in recipe_counts.items():
        assert count <= 2, f"Recipe {recipe_id} used {count} times, expected <= 2"
        assert count < 5, "Requirement: no 5 same meals in week"


def test_recent_week_weight_penalty_applied(db_session, test_user, monkeypatch):
    """
    Recipes used in the previous week should receive a 50% weight penalty.
    """
    r_recent = Recipe(
        name="Recent",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=1.0,
        dinner_weight=1.0,
    )
    r_other = Recipe(
        name="Other",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=1.0,
        dinner_weight=1.0,
    )
    db_session.add_all([r_recent, r_other])
    db_session.commit()

    start_date = datetime(2025, 1, 15, 12, 0, 0)
    past_plan = MealPlan(
        user_id=test_user.id,
        start_date=start_date - timedelta(days=7),
        end_date=start_date - timedelta(days=1),
        people_count=1,
        target_calories=1500,
        dietary_preferences=[],
    )
    db_session.add(past_plan)
    db_session.commit()
    db_session.refresh(past_plan)

    entry = MealPlanEntry(
        meal_plan_id=past_plan.id,
        recipe_id=r_recent.id,
        date=start_date - timedelta(days=2),
        meal_type="breakfast",
        servings=1,
    )
    db_session.add(entry)
    db_session.commit()

    generator = MealPlanGenerator(db_session)
    generator.recent_recipe_ids = generator._load_recent_recipe_ids(test_user.id, start_date)
    assert r_recent.id in generator.recent_recipe_ids

    captured = {}

    def fake_choices(seq, weights, k):
        captured["weights"] = weights
        return [seq[0]]

    monkeypatch.setattr(mpg.random, "choices", fake_choices)
    generator._select_recipe("breakfast", [r_recent, r_other], 500, 1.0)

    assert captured["weights"][0] == 0.5
    assert captured["weights"][1] == 1.0


def test_sanity_checks(db_session, test_user):
    """
    General sanity checks.
    """
    create_recipes(db_session, 5, "General", 500, {"breakfast": 1.0, "lunch": 1.0, "dinner": 1.0})

    generator = MealPlanGenerator(db_session)
    plan = generator.generate_meal_plan(
        start_date=datetime.now(),
        days=1,
        target_calories=1500,
        people_count=1,
        dietary_preferences=[],
        user_id=test_user.id,
    )

    assert plan.people_count == 1
    assert len(plan.entries) == 3
    types = [e.meal_type for e in plan.entries]
    assert "breakfast" in types
    assert "lunch" in types
    assert "dinner" in types


def test_no_suitable_recipes_raises_error(db_session, test_user):
    """
    Test that if no recipes exist, it raises ValueError.
    """
    # Create no recipes
    db_session.query(Recipe).delete()
    db_session.commit()

    generator = MealPlanGenerator(db_session)

    with pytest.raises(ValueError, match="No recipes available"):
        generator.generate_meal_plan(
            start_date=datetime.now(),
            days=1,
            target_calories=1500,
            people_count=1,
            dietary_preferences=[],
            user_id=test_user.id,
        )


def test_suggest_meal_excludes_current_recipe(db_session, test_user):
    """Re-roll must return a different recipe than the one currently in the slot."""
    recipes = create_recipes(db_session, 4, "B", 400, {"breakfast": 1.0})
    current = recipes[0]

    generator = MealPlanGenerator(db_session)
    for _ in range(15):
        suggestion = generator.suggest_meal(
            meal_type="breakfast",
            target_calories=1600,
            plan_recipe_ids=[current.id],
            current_recipe_id=current.id,
        )
        assert suggestion.id != current.id


def test_suggest_meal_respects_max_two_uses(db_session, test_user):
    """A recipe already used twice in the rest of the plan must not be suggested."""
    recipes = create_recipes(db_session, 3, "B", 400, {"breakfast": 1.0})
    current, capped, free = recipes

    generator = MealPlanGenerator(db_session)
    # `capped` appears twice in the rest of the plan -> over the limit. Only `free` is valid.
    for _ in range(15):
        suggestion = generator.suggest_meal(
            meal_type="breakfast",
            target_calories=1600,
            plan_recipe_ids=[capped.id, capped.id],
            current_recipe_id=current.id,
        )
        assert suggestion.id == free.id


def test_suggest_meal_snack_without_weight_column(db_session, test_user):
    """Snacks have no `snack_weight`; suggestion should still work (flat selection)."""
    recipes = create_recipes(db_session, 3, "Any", 300, {"breakfast": 1.0})
    valid_ids = {r.id for r in recipes}

    generator = MealPlanGenerator(db_session)
    suggestion = generator.suggest_meal(
        meal_type="snack",
        target_calories=2000,
        plan_recipe_ids=[],
        current_recipe_id=None,
    )
    assert suggestion.id in valid_ids


def test_no_same_meal_in_one_day(db_session, test_user):
    """
    Test that the same recipe is not selected multiple times in a single day.
    """
    # Create one recipe that fits all meals
    r1 = Recipe(
        name="Universal Meal",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=1.0,
        dinner_weight=1.0,
    )
    # Create another recipe to allow variety if needed,
    # but we want to ensure r1 isn't picked 3 times even if it's the only one?
    # If r1 is the only one, the generator might fail or be forced to pick it?
    # MealPlanGenerator excludes previously selected IDs in the same day.
    # So if only 1 recipe exists, it will fail to find a recipe for lunch/dinner?
    # Let's see behavior. If it fails, that confirms it tries to avoid duplicates.

    db_session.add(r1)
    db_session.commit()

    generator = MealPlanGenerator(db_session)

    # If we have only 1 recipe, and we try to generate 1 day (3 meals).
    # Breakfast picks r1.
    # Lunch excludes r1. No recipes left.
    # _select_recipe will try to pick from empty list?
    # _select_recipe filters available_recipes. If empty, it might crash or return None?
    # Looking at code: `available_recipes = [r for r ... if r.id not in exclude_ids ...]`
    # If empty, `suitable_recipes` empty.
    # `min(available_recipes, ...)` will crash if available_recipes is empty.

    # So we need at least 3 recipes to satisfy "unique meals per day" requirement if we want success.

    r2 = Recipe(
        name="Meal 2",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=1.0,
        dinner_weight=1.0,
    )
    r3 = Recipe(
        name="Meal 3",
        servings=1,
        instructions="x",
        calories=500,
        breakfast_weight=1.0,
        lunch_weight=1.0,
        dinner_weight=1.0,
    )
    db_session.add_all([r2, r3])
    db_session.commit()

    plan = generator.generate_meal_plan(
        start_date=datetime.now(),
        days=1,
        target_calories=1500,
        people_count=1,
        dietary_preferences=[],
        user_id=test_user.id,
    )

    # Verify entries for the day are unique recipes
    recipe_ids = [e.recipe_id for e in plan.entries]
    assert len(recipe_ids) == 3
    assert len(set(recipe_ids)) == 3, f"Duplicate recipes found in one day: {recipe_ids}"
