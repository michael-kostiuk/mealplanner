from app import models
from app.services.recipe_nutrition import DEFAULT_PIECE_GRAMS, compute_recipe_nutrition


def _ingredient(name, calories, base_unit="g"):
    return models.Ingredient(
        name=name,
        category="vegetables",
        base_unit=base_unit,
        calories=calories,
        protein=10,
        carbs=20,
        fats=5,
        portions=[],
    )


def _line(ingredient, quantity, unit):
    return models.RecipeIngredient(ingredient=ingredient, quantity=quantity, unit=unit)


def test_grams_per_serving_and_to_taste_ignored():
    rice = _ingredient("Rice", 100)
    salt = _ingredient("Salt", 0)
    nutrition = compute_recipe_nutrition(
        [_line(rice, 200, "g"), _line(salt, 0, "to taste")], servings=2
    )
    assert nutrition == {"calories": 100, "protein": 10.0, "carbs": 20.0, "fats": 5.0}


def test_piece_without_known_weight_counts_as_medium():
    beet = _ingredient("Beet", 50)
    nutrition = compute_recipe_nutrition([_line(beet, 2, "piece")], servings=1)
    assert nutrition["calories"] == round(2 * DEFAULT_PIECE_GRAMS * 50 / 100)


def test_volume_ingredient_counts_millilitres():
    vinegar = _ingredient("Vinegar", 20, base_unit="ml")
    nutrition = compute_recipe_nutrition([_line(vinegar, 1, "l")], servings=1)
    assert nutrition["calories"] == 200


def test_nothing_to_compute_from():
    salt = _ingredient("Salt", 0)
    assert compute_recipe_nutrition([_line(salt, 0, "to taste")], servings=4) is None
