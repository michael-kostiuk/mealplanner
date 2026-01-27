"""
FDC linking and portion extraction service.

This module provides functionality to:
1. Search FDC database and return best match with confidence score
2. Parse FDC portion data into IngredientPortion records
3. Link ingredients to FDC foods and populate portions
"""

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import models
from app.services.fdc_lookup import (
    get_data_type_weight,
    get_fdc_connection,
    load_synonyms,
    normalize_text,
    score_fdc_candidate,
)

logger = logging.getLogger(__name__)

# Minimum confidence threshold for auto-linking (0.85 = 85%)
MIN_CONFIDENCE_THRESHOLD = 0.85

# Mapping from FDC modifier strings to normalized units
# Size-based modifiers map to "piece"
MODIFIER_TO_UNIT = {
    # Size-based (map to piece)
    "medium": "piece",
    "large": "piece",
    "small": "piece",
    "whole": "piece",
    # Direct unit mappings
    "clove": "clove",
    "slice": "slice",
    "tbsp": "tbsp",
    "tablespoon": "tbsp",
    "tsp": "tsp",
    "teaspoon": "tsp",
    "cup": "cup",
    "can": "can",
    "bunch": "bunch",
    "package": "package",
}

# Keywords that indicate a size modifier (maps to "piece" unit)
SIZE_KEYWORDS = {"small", "medium", "large", "whole", "mini", "extra-large", "jumbo"}

# Keywords that indicate it's the item itself (like "tomato", "apple")
# These map to "piece" unit
ITEM_KEYWORDS = {
    "tomato",
    "apple",
    "banana",
    "egg",
    "onion",
    "potato",
    "carrot",
    "lemon",
    "lime",
    "orange",
}


@dataclass
class FdcMatch:
    """Result of FDC search with confidence score."""

    fdc_id: int
    description: str
    portions_json: str | None
    confidence: float


@dataclass
class ParsedPortion:
    """Parsed portion data ready for database insertion."""

    unit: str
    gram_weight: float
    modifier: str | None
    is_default: bool


def _extract_unit_from_modifier(modifier: str) -> tuple[str | None, str | None, bool]:
    """
    Extract unit and modifier info from FDC modifier string.

    Returns: (unit, size_modifier, is_default)
    - unit: normalized unit string (e.g., "piece", "cup", "slice")
    - size_modifier: size modifier if present (e.g., "medium", "large")
    - is_default: True if this should be the default for the unit
    """
    if not modifier:
        return None, None, False

    modifier_lower = modifier.lower().strip()

    # Check for direct unit matches first
    for key, unit in MODIFIER_TO_UNIT.items():
        if (
            modifier_lower == key
            or modifier_lower.startswith(f"{key} ")
            or f" {key}" in modifier_lower
        ):
            # Check if there's also a size modifier
            size_mod = None
            is_default = False
            for size in SIZE_KEYWORDS:
                if size in modifier_lower:
                    size_mod = size
                    is_default = size == "medium"
                    break
            return unit, size_mod, is_default

    # Check for size keywords (implies "piece" unit)
    for size in SIZE_KEYWORDS:
        if size in modifier_lower:
            return "piece", size, (size == "medium")

    # Check for item keywords (like "tomato" alone means 1 piece)
    for item in ITEM_KEYWORDS:
        if item in modifier_lower:
            # Check for size modifier
            size_mod = None
            is_default = False
            for size in SIZE_KEYWORDS:
                if size in modifier_lower:
                    size_mod = size
                    is_default = size == "medium"
                    break
            return "piece", size_mod, is_default

    # Check for cup variants
    if "cup" in modifier_lower:
        return "cup", None, False

    # Check for slice
    if "slice" in modifier_lower:
        return "slice", None, False

    # Check for wedge (treat as piece)
    if "wedge" in modifier_lower:
        return "piece", "wedge", False

    # Check for cherry (for cherry tomatoes - treat as piece)
    if "cherry" in modifier_lower:
        return "piece", "cherry", False

    # Check for serving (skip these as they're not useful for conversion)
    if "serving" in modifier_lower or "nlea" in modifier_lower:
        return None, None, False

    return None, None, False


def parse_fdc_portions(portions_json: str | None) -> list[ParsedPortion]:
    """
    Parse FDC portions JSON into ParsedPortion objects.

    Handles deduplication: if same unit appears multiple times,
    keeps the first one (or the one marked as default).
    """
    if not portions_json:
        return []

    try:
        portions = json.loads(portions_json)
    except json.JSONDecodeError:
        logger.warning("Failed to parse portions JSON")
        return []

    if not isinstance(portions, list):
        return []

    # Track portions by unit to handle duplicates
    unit_portions: dict[str, ParsedPortion] = {}

    for p in portions:
        gram_weight = p.get("gram_weight")
        if not gram_weight or gram_weight <= 0:
            continue

        # Try to extract unit from modifier first, then measure_unit
        modifier_str = p.get("modifier", "")
        unit, size_mod, is_default = _extract_unit_from_modifier(modifier_str)

        # If modifier didn't yield a unit, try measure_unit
        if not unit:
            measure_unit = p.get("measure_unit", "").lower().strip()
            amount = p.get("amount", 1.0)

            if measure_unit == "cup":
                unit = "cup"
                # Adjust gram_weight if amount != 1
                if amount and amount != 1:
                    gram_weight = gram_weight / amount
            elif measure_unit in ("tomatoes", "tomato", "pieces", "piece", "units", "unit"):
                unit = "piece"
                # Adjust gram_weight if amount != 1 (e.g., "5 tomatoes = 49.7g" -> 1 piece = 9.94g)
                if amount and amount != 1:
                    gram_weight = gram_weight / amount

        if not unit:
            continue

        portion = ParsedPortion(
            unit=unit,
            gram_weight=float(gram_weight),
            modifier=size_mod,
            is_default=is_default,
        )

        # Handle duplicates: prefer default, then first occurrence
        if unit not in unit_portions or is_default and not unit_portions[unit].is_default:
            unit_portions[unit] = portion

    return list(unit_portions.values())


def search_fdc_best_match(
    name: str,
    base_unit: str | None = None,
    allow_ascii: bool = False,
) -> FdcMatch | None:
    """
    Search FDC database for best match and return with confidence score.

    Uses existing _search logic from fdc_lookup.py but adds confidence calculation.

    Args:
        name: Ingredient name to search for
        base_unit: Optional base unit hint
        allow_ascii: Deprecated; kept for backward compatibility.

    Returns:
        FdcMatch with fdc_id, description, portions_json, and confidence score,
        or None if no match found.
    """
    try:
        conn = get_fdc_connection()
    except Exception as e:
        logger.warning("FDC database not available: %s", e)
        return None

    # Load synonyms for translation
    from app.services.fdc_lookup import _synonyms

    global_synonyms = _synonyms if _synonyms else load_synonyms()

    normalized = normalize_text(name)
    synonyms_hit = global_synonyms.get(normalized, normalized)

    tokens = [t for t in normalize_text(synonyms_hit).split() if t]
    if not tokens:
        return None

    # For scoring, we use the same tokens as search (no mandatory "raw" requirement)
    # The scoring function already gives bonus for "raw" in description
    scoring_tokens = list(tokens)

    # Build FTS query with wildcards
    # Simple approach: just use wildcard search
    query = " ".join(f"{t}*" for t in tokens)

    # Build alternate queries for plural/singular variations
    # This handles cases where FDC has singular but we search plural (or vice versa)
    alternate_queries = []
    if len(tokens) == 1:
        token = tokens[0]
        if token.endswith("ies"):
            # cherries -> cherry
            singular = token[:-3] + "y"
            alternate_queries.append(f"{singular}*")
        elif token.endswith("es"):
            # tomatoes -> tomato
            singular = token[:-2]
            alternate_queries.append(f"{singular}*")
        elif token.endswith("s") and len(token) > 2:
            # cashews -> cashew
            singular = token[:-1]
            alternate_queries.append(f"{singular}*")
        elif token.endswith("y"):
            # cherry -> cherries
            plural = token[:-1] + "ies"
            alternate_queries.append(f"{plural}*")

    rows = []
    try:
        # Use FTS for initial filtering, then order by data_type to prioritize foundation foods
        cursor = conn.execute(
            """
            SELECT f.fdc_id, f.description, f.portions_json, f.data_type
            FROM foods f
            JOIN foods_fts fts ON f.rowid = fts.rowid
            WHERE fts.search_name MATCH ?
            ORDER BY
                CASE WHEN f.data_type LIKE 'foundation%' THEN 0 ELSE 1 END,
                length(f.description)
            LIMIT 100
            """,
            (query,),
        )
        rows = list(cursor.fetchall())

        # Also search with alternate queries (singular/plural variations)
        for alt_query in alternate_queries:
            cursor = conn.execute(
                """
                SELECT f.fdc_id, f.description, f.portions_json, f.data_type
                FROM foods f
                JOIN foods_fts fts ON f.rowid = fts.rowid
                WHERE fts.search_name MATCH ?
                ORDER BY
                    CASE WHEN f.data_type LIKE 'foundation%' THEN 0 ELSE 1 END,
                    length(f.description)
                LIMIT 100
                """,
                (alt_query,),
            )
            # Merge results, avoiding duplicates
            existing_ids = {r["fdc_id"] for r in rows}
            for r in cursor.fetchall():
                if r["fdc_id"] not in existing_ids:
                    rows.append(r)
    except Exception as e:
        logger.warning("FDC FTS search failed: %s", e)
        return None

    if not rows:
        # Fallback to LIKE search
        like_clauses = " AND ".join("search_name LIKE ?" for _ in tokens)
        params = [f"%{t}%" for t in tokens]
        try:
            cursor = conn.execute(
                f"""
                SELECT fdc_id, description, portions_json, data_type
                FROM foods
                WHERE {like_clauses}
                ORDER BY
                    CASE WHEN data_type LIKE 'foundation%' THEN 0 ELSE 1 END,
                    length(description)
                LIMIT 100
                """,
                params,
            )
            rows = cursor.fetchall()
        except Exception as e:
            logger.warning("FDC LIKE search failed: %s", e)
            return None

    if not rows:
        return None

    # Score candidates
    scored = []
    for r in rows:
        score = score_fdc_candidate(r["description"], scoring_tokens)
        if score is None:
            continue
        score += get_data_type_weight(r)
        scored.append((score, r))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_row = scored[0]

    # Calculate confidence (normalize score to 0-1 range)
    # Score components:
    # - Token match: ~10 points per token, minus penalty for extra description tokens
    # - First token bonus: +15 if first search token matches first description token
    # - Data type bonus: up to 6 points (foundation) or 3 (sr_legacy)
    # - "raw" bonus: 3 points
    #
    # For confidence, we want a match with all tokens found + good data type to score high
    # We don't require the first-token bonus or raw bonus for high confidence
    max_expected_score = len(tokens) * 10 + 6  # tokens + max data_type bonus
    confidence = min(1.0, best_score / max_expected_score)

    return FdcMatch(
        fdc_id=best_row["fdc_id"],
        description=best_row["description"],
        portions_json=best_row["portions_json"],
        confidence=confidence,
    )


def link_ingredient_to_fdc(
    ingredient: models.Ingredient,
    db: Session,
    min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
) -> bool:
    """
    Attempt to link an ingredient to FDC and populate portions (sync version).

    This version does NOT use translation - it only works for English ingredient names
    or names that have synonym mappings. For Ukrainian/non-English ingredients,
    use link_ingredient_to_fdc_async which uses AI translation.

    Args:
        ingredient: The ingredient to link
        db: Database session
        min_confidence: Minimum confidence threshold for linking

    Returns:
        True if successfully linked, False otherwise
    """
    match = search_fdc_best_match(ingredient.name, ingredient.base_unit)

    if not match:
        logger.debug("No FDC match found for ingredient %s", ingredient.name)
        return False

    if match.confidence < min_confidence:
        logger.debug(
            "FDC match confidence %.2f below threshold %.2f for ingredient %s",
            match.confidence,
            min_confidence,
            ingredient.name,
        )
        return False

    return _apply_fdc_match(ingredient, match, db)


async def link_ingredient_to_fdc_async(
    ingredient: models.Ingredient,
    db: Session,
    min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
) -> bool:
    """
    Attempt to link an ingredient to FDC and populate portions (async version with translation).

    This version uses AI translation to convert Ukrainian/non-English ingredient names
    to English before searching FDC. This provides better matching for non-English ingredients.

    Args:
        ingredient: The ingredient to link
        db: Database session
        min_confidence: Minimum confidence threshold for linking

    Returns:
        True if successfully linked, False otherwise
    """
    from app.services.ingredient_translator import (
        IngredientTranslationError,
        get_ingredient_translator,
    )

    lookup_name = ingredient.name

    # Try to translate non-English ingredient names
    try:
        translator = get_ingredient_translator()
        translated = await translator.translate_to_english(ingredient.name)
        if translated:
            lookup_name = translated
            logger.debug(
                "Translated ingredient %s -> %s for FDC lookup",
                ingredient.name,
                translated,
            )
    except ValueError as exc:
        logger.warning(
            "Ingredient translation unavailable for ingredient %s: %s",
            ingredient.id,
            exc,
        )
    except IngredientTranslationError as exc:
        logger.warning(
            "Ingredient translation failed for ingredient %s: %s",
            ingredient.id,
            exc.message,
        )
    except Exception as exc:
        logger.warning(
            "Ingredient translation failed for ingredient %s: %s",
            ingredient.id,
            exc,
        )

    # Search FDC with potentially translated name
    match = search_fdc_best_match(lookup_name, ingredient.base_unit, allow_ascii=True)

    if not match:
        logger.debug(
            "No FDC match found for ingredient %s (searched: %s)", ingredient.name, lookup_name
        )
        return False

    if match.confidence < min_confidence:
        logger.debug(
            "FDC match confidence %.2f below threshold %.2f for ingredient %s",
            match.confidence,
            min_confidence,
            ingredient.name,
        )
        return False

    return _apply_fdc_match(ingredient, match, db)


def _apply_fdc_match(
    ingredient: models.Ingredient,
    match: FdcMatch,
    db: Session,
) -> bool:
    """
    Apply an FDC match to an ingredient - set fdc_id and create portions.

    Args:
        ingredient: The ingredient to update
        match: The FDC match to apply
        db: Database session

    Returns:
        True (always succeeds if called)
    """
    # Update ingredient with FDC link
    ingredient.fdc_id = match.fdc_id

    # Parse and create portions
    parsed_portions = parse_fdc_portions(match.portions_json)

    for p in parsed_portions:
        portion = models.IngredientPortion(
            ingredient_id=ingredient.id,
            unit=p.unit,
            gram_weight=p.gram_weight,
            modifier=p.modifier,
            is_default=p.is_default,
        )
        db.add(portion)

    logger.info(
        "Linked ingredient %s (id=%d) to FDC %d (%s) with %d portions (confidence=%.2f)",
        ingredient.name,
        ingredient.id,
        match.fdc_id,
        match.description,
        len(parsed_portions),
        match.confidence,
    )

    return True


def get_gram_weight(ingredient: models.Ingredient, unit: str) -> float | None:
    """
    Get gram weight for a unit from ingredient's portions.

    Args:
        ingredient: Ingredient with portions loaded
        unit: Normalized unit string

    Returns:
        Gram weight if found, None otherwise
    """
    if not ingredient.portions:
        return None

    # First, look for default portion with matching unit
    for portion in ingredient.portions:
        if portion.unit == unit and portion.is_default:
            return portion.gram_weight

    # Fall back to any portion with matching unit
    for portion in ingredient.portions:
        if portion.unit == unit:
            return portion.gram_weight

    return None
