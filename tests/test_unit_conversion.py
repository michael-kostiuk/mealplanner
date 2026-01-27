"""
Tests for ingredient unit conversion and shopping list aggregation.

Tests the scenarios from PLAN_INGREDIENT_CONVERSION.md:
- Same Family: 500g butter + 0.5kg butter = 1kg butter
- Count to Mass: 1 piece tomato + 300g tomato = 423g tomato (with FDC data)
- No FDC Link: ingredients without FDC = separate lines
- Same Count Unit: 2 cans + 1 can = 3 cans
- Mixed Count and Mass: 2 cans + 400g = converted via FDC
- Partial Conversion: some units convert, some don't
- Volume Units: cup to grams via FDC
- Large Quantities: 800g + 500g = 1.3kg
"""

import pytest

from app import models
from app.services.unit_converter import (
    QuantityUnit,
    _to_grams_static,
    aggregate_quantities,
    format_quantity,
)


@pytest.fixture
def ingredient_with_portions(db_session):
    """Create an ingredient with FDC portions for testing."""
    ingredient = models.Ingredient(
        name="Tomato",
        category="Vegetables",
        base_unit="g",
        fdc_id=170457,
        calories=18,
        protein=0.9,
        carbs=3.9,
        fats=0.2,
    )
    db_session.add(ingredient)
    db_session.commit()
    db_session.refresh(ingredient)

    # Add portions (simulating FDC data)
    portions = [
        models.IngredientPortion(
            ingredient_id=ingredient.id,
            unit="piece",
            gram_weight=123.0,  # medium tomato
            modifier="medium",
            is_default=True,
        ),
        models.IngredientPortion(
            ingredient_id=ingredient.id,
            unit="cup",
            gram_weight=180.0,  # chopped
            modifier=None,
            is_default=False,
        ),
        models.IngredientPortion(
            ingredient_id=ingredient.id,
            unit="slice",
            gram_weight=20.0,
            modifier=None,
            is_default=False,
        ),
    ]
    for p in portions:
        db_session.add(p)
    db_session.commit()
    db_session.refresh(ingredient)

    return ingredient


@pytest.fixture
def ingredient_without_portions(db_session):
    """Create an ingredient without FDC link."""
    ingredient = models.Ingredient(
        name="Exotic Fruit",
        category="Fruits",
        base_unit="piece",
        fdc_id=None,
        calories=50,
        protein=1,
        carbs=12,
        fats=0.5,
    )
    db_session.add(ingredient)
    db_session.commit()
    db_session.refresh(ingredient)
    return ingredient


@pytest.fixture
def ingredient_with_can_portion(db_session):
    """Create an ingredient with can portion (like diced tomatoes)."""
    ingredient = models.Ingredient(
        name="Diced Tomatoes",
        category="Canned",
        base_unit="g",
        fdc_id=12345,
        calories=20,
        protein=1,
        carbs=4,
        fats=0,
    )
    db_session.add(ingredient)
    db_session.commit()
    db_session.refresh(ingredient)

    portion = models.IngredientPortion(
        ingredient_id=ingredient.id,
        unit="can",
        gram_weight=400.0,  # standard 400g can
        modifier=None,
        is_default=True,
    )
    db_session.add(portion)
    db_session.commit()
    db_session.refresh(ingredient)

    return ingredient


@pytest.fixture
def butter_ingredient(db_session):
    """Create butter ingredient for mass conversion tests."""
    ingredient = models.Ingredient(
        name="Butter",
        category="Dairy",
        base_unit="g",
        fdc_id=1001,
        calories=717,
        protein=0.9,
        carbs=0.1,
        fats=81,
    )
    db_session.add(ingredient)
    db_session.commit()
    db_session.refresh(ingredient)
    return ingredient


@pytest.fixture
def flour_ingredient(db_session):
    """Create flour ingredient with cup portion."""
    ingredient = models.Ingredient(
        name="All-Purpose Flour",
        category="Baking",
        base_unit="g",
        fdc_id=20081,
        calories=364,
        protein=10,
        carbs=76,
        fats=1,
    )
    db_session.add(ingredient)
    db_session.commit()
    db_session.refresh(ingredient)

    portion = models.IngredientPortion(
        ingredient_id=ingredient.id,
        unit="cup",
        gram_weight=125.0,
        modifier=None,
        is_default=True,
    )
    db_session.add(portion)
    db_session.commit()
    db_session.refresh(ingredient)

    return ingredient


class TestFormatQuantity:
    """Test quantity formatting for display."""

    def test_small_grams(self):
        """< 1000g should display as grams."""
        qty, unit = format_quantity(450)
        assert qty == 450
        assert unit == "g"

    def test_large_grams_to_kg(self):
        """≥ 1000g should display as kg."""
        qty, unit = format_quantity(1300)
        assert qty == 1.3
        assert unit == "kg"

    def test_exact_kg(self):
        """1000g = 1kg (no decimal)."""
        qty, unit = format_quantity(1000)
        assert qty == 1.0
        assert unit == "kg"

    def test_large_kg(self):
        """2500g = 2.5kg."""
        qty, unit = format_quantity(2500)
        assert qty == 2.5
        assert unit == "kg"


class TestStaticMassConversion:
    """Test static mass unit conversions (g, kg)."""

    def test_grams_passthrough(self):
        """g -> g is 1:1."""
        assert _to_grams_static(100, "g") == 100

    def test_kg_to_grams(self):
        """kg -> g multiplies by 1000."""
        assert _to_grams_static(0.5, "kg") == 500

    def test_unknown_unit(self):
        """Unknown units return None."""
        assert _to_grams_static(100, "cup") is None
        assert _to_grams_static(100, "piece") is None


class TestScenario1SameFamily:
    """Scenario 1: Same unit family (mass)."""

    def test_same_family_grams_and_kg(self, butter_ingredient):
        """500g butter + 0.5kg butter = 1kg butter."""
        items = [
            QuantityUnit(quantity=500, unit="g"),
            QuantityUnit(quantity=0.5, unit="kg"),
        ]

        result = aggregate_quantities(items, butter_ingredient)

        assert result.main_quantity == 1.0
        assert result.main_unit == "kg"
        assert len(result.unconvertible) == 0


class TestScenario2CountToMass:
    """Scenario 2: Count unit to mass via FDC."""

    def test_piece_plus_grams(self, ingredient_with_portions):
        """1 piece tomato + 300g tomato = 423g (medium tomato = 123g)."""
        items = [
            QuantityUnit(quantity=1, unit="piece"),
            QuantityUnit(quantity=300, unit="g"),
        ]

        result = aggregate_quantities(items, ingredient_with_portions)

        # 1 * 123g + 300g = 423g
        assert result.main_quantity == 423
        assert result.main_unit == "g"
        assert len(result.unconvertible) == 0


class TestScenario3NoFdcLink:
    """Scenario 3: No FDC link - keep separate lines."""

    def test_no_conversion_without_fdc(self, ingredient_without_portions):
        """1 piece + 200g without FDC = two separate lines."""
        items = [
            QuantityUnit(quantity=1, unit="piece"),
            QuantityUnit(quantity=200, unit="g"),
        ]

        result = aggregate_quantities(items, ingredient_without_portions)

        # The grams should be the main quantity
        assert result.main_quantity == 200
        assert result.main_unit == "g"
        # The piece should be unconvertible
        assert len(result.unconvertible) == 1
        assert result.unconvertible[0].quantity == 1
        assert result.unconvertible[0].unit == "piece"


class TestScenario4SameCountUnit:
    """Scenario 4: Same count unit stays as count."""

    def test_same_count_unit(self, ingredient_with_can_portion):
        """2 cans + 1 can = 3 cans."""
        items = [
            QuantityUnit(quantity=2, unit="can"),
            QuantityUnit(quantity=1, unit="can"),
        ]

        result = aggregate_quantities(items, ingredient_with_can_portion)

        assert result.main_quantity == 3
        assert result.main_unit == "can"
        assert len(result.unconvertible) == 0


class TestScenario4bMixedCountAndMass:
    """Scenario 4b: Mixed count and mass converts via FDC."""

    def test_cans_plus_grams(self, ingredient_with_can_portion):
        """2 cans + 400g = 1.2kg (1 can = 400g)."""
        items = [
            QuantityUnit(quantity=2, unit="can"),
            QuantityUnit(quantity=400, unit="g"),
        ]

        result = aggregate_quantities(items, ingredient_with_can_portion)

        # 2 * 400g + 400g = 1200g = 1.2kg
        assert result.main_quantity == 1.2
        assert result.main_unit == "kg"
        assert len(result.unconvertible) == 0


class TestScenario5PartialConversion:
    """Scenario 5: Partial conversion with unconvertible units."""

    def test_partial_with_pinch(self, flour_ingredient):
        """100g flour + 2 cups flour + 1 pinch flour."""
        items = [
            QuantityUnit(quantity=100, unit="g"),
            QuantityUnit(quantity=2, unit="cup"),
            QuantityUnit(quantity=1, unit="pinch"),
        ]

        result = aggregate_quantities(items, flour_ingredient)

        # 100g + 2*125g = 350g
        assert result.main_quantity == 350
        assert result.main_unit == "g"
        # pinch is unconvertible
        assert len(result.unconvertible) == 1
        assert result.unconvertible[0].quantity == 1
        assert result.unconvertible[0].unit == "pinch"


class TestScenario8SameUnconvertibleUnits:
    """Scenario 8: Same unconvertible unit should combine to a single line."""

    def test_same_unit_combines(self, butter_ingredient):
        items = [
            QuantityUnit(quantity=1, unit="tsp"),
            QuantityUnit(quantity=1, unit="tsp"),
        ]

        result = aggregate_quantities(items, butter_ingredient)

        assert result.main_quantity == 2
        assert result.main_unit == "tsp"
        assert len(result.unconvertible) == 0


class TestScenario6VolumeUnits:
    """Scenario 6: Volume units via FDC."""

    def test_cup_to_grams(self, ingredient_with_portions):
        """1 cup tomato = 180g (via FDC portion)."""
        items = [
            QuantityUnit(quantity=1, unit="cup"),
            QuantityUnit(quantity=100, unit="g"),
        ]

        result = aggregate_quantities(items, ingredient_with_portions)

        # 1 * 180g + 100g = 280g
        assert result.main_quantity == 280
        assert result.main_unit == "g"


class TestScenario7LargeQuantities:
    """Scenario 7: Large quantities display as kg."""

    def test_large_grams_to_kg(self, butter_ingredient):
        """800g + 500g = 1.3kg."""
        items = [
            QuantityUnit(quantity=800, unit="g"),
            QuantityUnit(quantity=500, unit="g"),
        ]

        result = aggregate_quantities(items, butter_ingredient)

        assert result.main_quantity == 1.3
        assert result.main_unit == "kg"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_items(self, butter_ingredient):
        """Empty items list returns 0g."""
        result = aggregate_quantities([], butter_ingredient)
        assert result.main_quantity == 0
        assert result.main_unit == "g"

    def test_only_unconvertible(self, butter_ingredient):
        """Only unconvertible items returns first as main."""
        items = [
            QuantityUnit(quantity=1, unit="pinch"),
            QuantityUnit(quantity=2, unit="to taste"),
        ]

        result = aggregate_quantities(items, butter_ingredient)

        # First unconvertible becomes main
        assert result.main_quantity == 1
        assert result.main_unit == "pinch"
        # Rest stay in unconvertible
        assert len(result.unconvertible) == 1
        assert result.unconvertible[0].unit == "to taste"

    def test_as_needed_unconvertible(self, butter_ingredient):
        """'as needed' unit is unconvertible."""
        items = [
            QuantityUnit(quantity=100, unit="g"),
            QuantityUnit(quantity=1, unit="as needed"),
        ]

        result = aggregate_quantities(items, butter_ingredient)

        assert result.main_quantity == 100
        assert result.main_unit == "g"
        assert len(result.unconvertible) == 1
        assert result.unconvertible[0].unit == "as needed"
