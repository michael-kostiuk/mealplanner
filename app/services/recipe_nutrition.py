"""
Per-serving nutrition of a recipe, computed from its ingredients.

Ingredient nutrition is stored per 100 of the ingredient's base unit (g, ml or a count
unit). Each recipe amount is brought to that base unit through the same conversions the
shopping list uses; "to taste" amounts count as nothing.
"""

from typing import TYPE_CHECKING

from app.services.fdc_linker import get_gram_weight
from app.services.unit_converter import ML_PER_UNIT, convert_to_grams, grams_per_ml
from app.units import (
    COUNT_UNITS,
    MASS_UNITS,
    UNCONVERTIBLE_UNITS,
    VOLUME_UNITS,
    BaseUnit,
    normalize_unit,
)

if TYPE_CHECKING:
    from app import models

# A piece of something with no known weight (no FDC portion) counts as a medium one
DEFAULT_PIECE_GRAMS = 100.0


def _grams(quantity: float, unit: str, ingredient: "models.Ingredient") -> float:
    grams = convert_to_grams(quantity, unit, ingredient)
    if grams is None and unit in COUNT_UNITS:
        grams = quantity * DEFAULT_PIECE_GRAMS
    return grams or 0.0


def _in_base_units(quantity: float, unit: str, ingredient: "models.Ingredient") -> float:
    """The amount expressed in the ingredient's base unit (what its nutrition is per 100 of)."""
    base = normalize_unit(ingredient.base_unit) or BaseUnit.G.value
    if unit == base:
        return quantity
    if base in VOLUME_UNITS:
        ml = quantity * ML_PER_UNIT[unit] if unit in ML_PER_UNIT else None
        if ml is None:
            ml = _grams(quantity, unit, ingredient) / grams_per_ml(ingredient)
        return ml / VOLUME_UNITS[base]
    if base in COUNT_UNITS:
        piece = get_gram_weight(ingredient, base) or DEFAULT_PIECE_GRAMS
        return _grams(quantity, unit, ingredient) / piece
    return _grams(quantity, unit, ingredient) / MASS_UNITS.get(base, 1.0)


def compute_recipe_nutrition(
    recipe_ingredients: list["models.RecipeIngredient"], servings: int
) -> dict[str, float] | None:
    """Calories, protein, carbs and fats per serving, or None when there is nothing to
    compute from (no ingredients with an amount)."""
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
    counted = 0
    for ri in recipe_ingredients:
        unit = normalize_unit(ri.unit) or BaseUnit.PIECE.value
        if unit in UNCONVERTIBLE_UNITS or not ri.quantity or ri.ingredient is None:
            continue
        factor = _in_base_units(ri.quantity, unit, ri.ingredient) / 100
        for field in totals:
            totals[field] += (getattr(ri.ingredient, field) or 0.0) * factor
        counted += 1
    if counted == 0:
        return None
    per = max(servings or 1, 1)
    return {
        "calories": round(totals["calories"] / per),
        "protein": round(totals["protein"] / per, 1),
        "carbs": round(totals["carbs"] / per, 1),
        "fats": round(totals["fats"] / per, 1),
    }
