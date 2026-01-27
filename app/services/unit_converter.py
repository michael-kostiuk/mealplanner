"""
Unit conversion service for shopping list aggregation.

This module provides functionality to convert quantities between different units
and aggregate shopping list items using FDC portion data.
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.fdc_linker import get_gram_weight
from app.units import COUNT_UNITS, MASS_UNITS, UNCONVERTIBLE_UNITS

if TYPE_CHECKING:
    from app import models

logger = logging.getLogger(__name__)


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
    3. Return None if cannot convert

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

    return None


def format_quantity(grams: float) -> tuple[float, str]:
    """
    Format gram quantity for human-friendly display.

    Rules:
    - >= 1000g: display as kg with decimal (e.g., 1.5kg)
    - < 1000g: display as grams (e.g., 450g)

    Returns:
        Tuple of (quantity, unit)
    """
    if grams >= 1000:
        kg = grams / 1000
        # Round to 1 decimal place
        kg = round(kg, 1)
        # Remove trailing .0
        if kg == int(kg):
            kg = int(kg)
        return float(kg), "kg"
    else:
        # Round to nearest integer for display
        g = round(grams)
        return float(g), "g"


def aggregate_quantities(
    items: list[QuantityUnit],
    ingredient: "models.Ingredient",
) -> AggregatedItem:
    """
    Aggregate multiple quantities of the same ingredient into a single result.

    Aggregation strategy:
    1. If all items use the same count unit: sum directly, keep as count
    2. If all can convert to grams: convert all and sum
    3. If some cannot convert: sum convertible to grams, keep others separate

    Args:
        items: List of (quantity, unit) pairs for the same ingredient
        ingredient: The ingredient with FDC portions loaded

    Returns:
        AggregatedItem with main quantity/unit and any unconvertible items
    """
    if not items:
        return AggregatedItem(
            ingredient_id=ingredient.id,
            ingredient_name=ingredient.name,
            category=ingredient.category,
            main_quantity=0,
            main_unit="g",
        )

    # Separate items by convertibility
    convertible_to_grams: list[tuple[float, str]] = []  # (original_qty, unit)
    count_items: dict[str, float] = {}  # unit -> total quantity
    unconvertible: list[QuantityUnit] = []

    for item in items:
        unit = item.unit
        qty = item.quantity

        # Check if unconvertible
        if unit in UNCONVERTIBLE_UNITS:
            unconvertible.append(item)
            continue

        # Check if it's a count unit
        if unit in COUNT_UNITS:
            count_items[unit] = count_items.get(unit, 0) + qty
            continue

        # Check if we can convert to grams
        grams = convert_to_grams(qty, unit, ingredient)
        if grams is not None:
            convertible_to_grams.append((grams, unit))
        else:
            unconvertible.append(item)

    # Determine aggregation strategy

    # Case 1: All items are the same count unit
    if len(count_items) == 1 and not convertible_to_grams:
        unit, total = list(count_items.items())[0]
        return AggregatedItem(
            ingredient_id=ingredient.id,
            ingredient_name=ingredient.name,
            category=ingredient.category,
            main_quantity=total,
            main_unit=unit,
            unconvertible=unconvertible,
        )

    # Case 2: Mix of count and mass/volume - try to convert count to grams
    total_grams = sum(g for g, _ in convertible_to_grams)

    for unit, qty in count_items.items():
        grams = _to_grams_via_fdc(qty, unit, ingredient)
        if grams is not None:
            total_grams += grams
        else:
            # Cannot convert this count unit - keep separate
            unconvertible.append(QuantityUnit(quantity=qty, unit=unit))

    # Format the result
    if total_grams > 0:
        display_qty, display_unit = format_quantity(total_grams)
        return AggregatedItem(
            ingredient_id=ingredient.id,
            ingredient_name=ingredient.name,
            category=ingredient.category,
            main_quantity=display_qty,
            main_unit=display_unit,
            unconvertible=unconvertible,
        )

    # No grams at all - return first unconvertible item as main
    if unconvertible:
        first = unconvertible.pop(0)
        return AggregatedItem(
            ingredient_id=ingredient.id,
            ingredient_name=ingredient.name,
            category=ingredient.category,
            main_quantity=first.quantity,
            main_unit=first.unit,
            unconvertible=unconvertible,
        )

    # Edge case: no items at all
    return AggregatedItem(
        ingredient_id=ingredient.id,
        ingredient_name=ingredient.name,
        category=ingredient.category,
        main_quantity=0,
        main_unit="g",
    )
