"""
Unit conversion service for shopping list aggregation.

This module provides functionality to convert quantities between different units
and aggregate shopping list items using FDC portion data.
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.fdc_linker import get_gram_weight
from app.units import (
    COUNT_UNITS,
    MASS_UNITS,
    SPOON_CUP_ML,
    UNCONVERTIBLE_UNITS,
    VOLUME_UNITS,
    BaseUnit,
    normalize_unit,
)

if TYPE_CHECKING:
    from app import models

logger = logging.getLogger(__name__)

# Millilitres in each volume unit (metric and spoon/cup)
ML_PER_UNIT = {**VOLUME_UNITS, **SPOON_CUP_ML}

# Density used when the ingredient has no FDC volume portion (water-like)
DEFAULT_GRAMS_PER_ML = 1.0


@dataclass
class QuantityUnit:
    """A quantity with its unit."""

    quantity: float
    unit: str


@dataclass
class AggregatedItem:
    """Result of aggregating an ingredient's quantities."""

    ingredient_id: int
    ingredient_name: str
    category: str | None
    # Main aggregated result
    main_quantity: float
    main_unit: str
    # Unconvertible items kept separate
    unconvertible: list[QuantityUnit] = field(default_factory=list)


def _combine_same_units(items: list[QuantityUnit]) -> list[QuantityUnit]:
    """Combine multiple QuantityUnit entries that share the same unit."""

    totals: dict[str, float] = {}
    order: list[str] = []
    for item in items:
        if item.unit is None:
            continue
        qty = float(item.quantity or 0)
        if item.unit not in totals:
            order.append(item.unit)
        totals[item.unit] = totals.get(item.unit, 0.0) + qty
    return [QuantityUnit(quantity=totals[unit], unit=unit) for unit in order]


def _to_grams_static(quantity: float, unit: str) -> float | None:
    """
    Convert quantity to grams using static conversion factors.
    Only works for mass units (g, kg).

    Returns None if unit is not a known mass unit.
    """
    if unit in MASS_UNITS:
        return quantity * MASS_UNITS[unit]
    return None


def _to_grams_via_fdc(
    quantity: float,
    unit: str,
    ingredient: "models.Ingredient",
) -> float | None:
    """
    Convert quantity to grams using FDC portion data.

    Works for count units (piece, slice, etc.) and volume units (cup, tbsp, etc.).

    Returns None if no FDC portion data available for this unit.
    """
    gram_weight = get_gram_weight(ingredient, unit)
    if gram_weight is not None:
        return quantity * gram_weight
    return None


def grams_per_ml(ingredient: "models.Ingredient") -> float:
    """
    Density of the ingredient, derived from any FDC spoon/cup portion.

    FDC rarely lists ml portions, but tbsp/tsp/cup weights give the density.
    Falls back to water density when no volume portion exists.
    """
    for portion in ingredient.portions or []:
        ml = SPOON_CUP_ML.get(portion.unit) or VOLUME_UNITS.get(portion.unit)
        if ml and portion.gram_weight:
            return portion.gram_weight / ml
    return DEFAULT_GRAMS_PER_ML


def _to_grams_via_volume(
    quantity: float,
    unit: str,
    ingredient: "models.Ingredient",
) -> float | None:
    """Convert a volume unit to grams through the ingredient's density."""
    ml = ML_PER_UNIT.get(unit)
    if ml is None:
        return None
    return quantity * ml * grams_per_ml(ingredient)


def convert_to_grams(
    quantity: float,
    unit: str,
    ingredient: "models.Ingredient",
) -> float | None:
    """
    Convert quantity to grams using best available method.

    Conversion strategy:
    1. Static mass conversion (g, kg)
    2. FDC portion lookup (piece, cup, tbsp, etc.)
    3. Volume via density (ml, l, spoons, cups; FDC-derived or 1 g/ml)
    4. Return None if cannot convert

    Args:
        quantity: The quantity to convert
        unit: The unit of the quantity (normalized)
        ingredient: The ingredient with FDC portions loaded

    Returns:
        Quantity in grams, or None if conversion not possible
    """
    # Check if unconvertible
    if unit in UNCONVERTIBLE_UNITS:
        return None

    # Try static mass conversion
    grams = _to_grams_static(quantity, unit)
    if grams is not None:
        return grams

    # Try FDC portion lookup
    grams = _to_grams_via_fdc(quantity, unit, ingredient)
    if grams is not None:
        return grams

    return _to_grams_via_volume(quantity, unit, ingredient)


def format_quantity(grams: float) -> tuple[float, str]:
    """
    Format gram quantity for human-friendly display.

    Rules:
    - >= 1000g: display as kg with decimal (e.g., 1.5kg)
    - < 1000g: display as grams (e.g., 450g)

    Returns:
        Tuple of (quantity, unit)
    """
    return _format_metric(grams, "g", "kg")


def _format_metric(amount: float, small_unit: str, large_unit: str) -> tuple[float, str]:
    """Format g/kg or ml/l: whole small units, or large units with one decimal."""
    if amount >= 1000:
        large = round(amount / 1000, 1)
        return float(large), large_unit
    return float(round(amount)), small_unit


def _target_unit(ingredient: "models.Ingredient") -> str:
    """The unit an ingredient is bought in: its base unit, normalized."""
    return normalize_unit(ingredient.base_unit) or BaseUnit.G.value


def _format_for_ingredient(grams: float, ingredient: "models.Ingredient") -> tuple[float, str]:
    """
    Express a gram total in the ingredient's base unit when it can be reached.

    - count base unit (eggs -> piece): needs an FDC portion for that unit
    - volume base unit (ml/l): uses the ingredient's density
    - anything else: g/kg
    """
    target = _target_unit(ingredient)

    if target in COUNT_UNITS:
        piece_weight = get_gram_weight(ingredient, target)
        if piece_weight:
            return round(grams / piece_weight, 1), target

    if target in VOLUME_UNITS:
        ml = grams / grams_per_ml(ingredient)
        return _format_metric(ml, BaseUnit.ML.value, BaseUnit.L.value)

    return format_quantity(grams)


def aggregate_quantities(
    items: list[QuantityUnit],
    ingredient: "models.Ingredient",
) -> AggregatedItem:
    """
    Aggregate multiple quantities of the same ingredient into a single result.

    Aggregation strategy:
    1. If all items use the same unit: sum directly and keep that unit
       (unless the ingredient is bought by count and can be converted to it)
    2. Otherwise convert everything possible to grams and sum
    3. Express the total in the ingredient's base unit where possible
    4. Keep anything that cannot be converted as separate lines

    Args:
        items: List of (quantity, unit) pairs for the same ingredient
        ingredient: The ingredient with FDC portions loaded

    Returns:
        AggregatedItem with main quantity/unit and any unconvertible items
    """

    def result(quantity: float, unit: str, unconvertible: list[QuantityUnit]) -> AggregatedItem:
        return AggregatedItem(
            ingredient_id=ingredient.id,
            ingredient_name=ingredient.name,
            category=ingredient.category,
            main_quantity=quantity,
            main_unit=unit,
            unconvertible=unconvertible,
        )

    if not items:
        return result(0, BaseUnit.G.value, [])

    # Pinch / to taste / as needed are never summed with anything else
    measurable = _combine_same_units([i for i in items if i.unit not in UNCONVERTIBLE_UNITS])
    unconvertible = _combine_same_units([i for i in items if i.unit in UNCONVERTIBLE_UNITS])

    if not measurable:
        first = unconvertible.pop(0)
        return result(first.quantity, first.unit, unconvertible)

    target = _target_unit(ingredient)

    # Case 1: a single non-mass unit - keep it, it is the most readable form
    # (2 tsp, 3 cans). Count-bought ingredients still convert: 2 tbsp eggs -> piece.
    # Mass goes through grams so it is shown as g/kg or in the base unit.
    if len(measurable) == 1:
        only = measurable[0]
        converts = only.unit in MASS_UNITS or (
            target in COUNT_UNITS
            and only.unit != target
            and get_gram_weight(ingredient, target) is not None
        )
        grams = convert_to_grams(only.quantity, only.unit, ingredient) if converts else None
        if grams is None:
            return result(only.quantity, only.unit, unconvertible)
        quantity, unit = _format_for_ingredient(grams, ingredient)
        return result(quantity, unit, unconvertible)

    # Case 2: mixed units - sum in grams, keep what cannot convert separate
    total_grams = 0.0
    leftovers: list[QuantityUnit] = []
    for item in measurable:
        grams = convert_to_grams(item.quantity, item.unit, ingredient)
        if grams is None:
            leftovers.append(item)
        else:
            total_grams += grams

    if total_grams <= 0:
        first = leftovers.pop(0)
        return result(first.quantity, first.unit, leftovers + unconvertible)

    quantity, unit = _format_for_ingredient(total_grams, ingredient)
    return result(quantity, unit, leftovers + unconvertible)
