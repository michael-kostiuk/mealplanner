import asyncio
import logging
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import SessionLocal, get_db
from ..services import fdc_lookup
from ..services.ingredient_translator import (
    IngredientTranslationError,
    get_ingredient_translator,
)
from ..services.nutrition_estimator import (
    IngredientInput,
    NutritionEstimationError,
    get_nutrition_estimator,
)
from ..units import BaseUnit, normalize_unit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ingredients",
    tags=["ingredients"],
)


def _is_nutrition_missing(ingredient: models.Ingredient) -> bool:
    """Check if all nutrition fields are zero or null."""
    return (
        (ingredient.calories is None or ingredient.calories == 0)
        and (ingredient.protein is None or ingredient.protein == 0)
        and (ingredient.carbs is None or ingredient.carbs == 0)
        and (ingredient.fats is None or ingredient.fats == 0)
    )


def _estimate_nutrition_background_sync(ingredient_id: int) -> None:
    """Synchronous background task to estimate nutrition for a newly created ingredient.

    Runs blocking DB/FDC operations in a thread pool to avoid blocking the event loop.
    Creates its own database session since the request session will be closed.
    """
    db = SessionLocal()
    try:
        ingredient = (
            db.query(models.Ingredient).filter(models.Ingredient.id == ingredient_id).first()
        )
        if not ingredient:
            logger.warning(
                "Background nutrition estimation: ingredient %s not found", ingredient_id
            )
            return

        # Double-check nutrition is still missing (might have been updated concurrently)
        if not _is_nutrition_missing(ingredient):
            logger.info(
                "Background nutrition estimation: ingredient %s already has nutrition data",
                ingredient_id,
            )
            return

        # Try FDC lookup first (sync operation)
        macros = _lookup_fdc_macros_sync(ingredient)
        if macros:
            logger.info(
                "Background nutrition estimation: ingredient %s matched via FDC", ingredient_id
            )
            _update_ingredient_from_macros(ingredient, macros, db)
            return

        # Fall back to AI estimation (requires async, run in new event loop)
        logger.info(
            "Background nutrition estimation: ingredient %s falling back to AI", ingredient_id
        )
        try:
            estimator = get_nutrition_estimator()
            # Run async estimation in a new event loop since we're in a sync context
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_estimate_and_update_ingredient(ingredient, estimator, db))
            finally:
                loop.close()
            logger.info(
                "Background nutrition estimation: ingredient %s completed via AI", ingredient_id
            )
        except ValueError as e:
            logger.warning(
                "Background nutrition estimation: AI estimator unavailable for ingredient %s: %s",
                ingredient_id,
                e,
            )
        except NutritionEstimationError as e:
            logger.warning(
                "Background nutrition estimation: AI estimation failed for ingredient %s: %s",
                ingredient_id,
                e.message,
            )
    except Exception as e:
        logger.exception(
            "Background nutrition estimation: unexpected error for ingredient %s: %s",
            ingredient_id,
            e,
        )
        db.rollback()
    finally:
        db.close()


def _lookup_fdc_macros_sync(ingredient: models.Ingredient) -> dict | None:
    """Synchronous version of FDC lookup for background tasks.

    Skips async translation since we're in a sync context.
    """
    try:
        normalized_unit = normalize_unit(ingredient.base_unit) or ingredient.base_unit
        return fdc_lookup.lookup_nutrition(
            ingredient.name,
            normalized_unit,
            allow_ascii=False,
        )
    except fdc_lookup.FdcLookupError as exc:
        logger.warning("FDC lookup unavailable for ingredient %s: %s", ingredient.id, exc)
        return None


async def _estimate_and_update_ingredient(
    ingredient: models.Ingredient,
    estimator,
    db: Session,
) -> models.Ingredient:
    """
    Use AI to estimate nutrition for a single ingredient and persist it.
    Assumes caller handles exception mapping.
    """
    unit = normalize_unit(ingredient.base_unit) or BaseUnit.PIECE.value
    input_item = IngredientInput(
        name=ingredient.name,
        quantity=100.0,
        unit=unit,
    )
    nutrition = await estimator.estimate_nutrition([input_item], servings=1)

    ingredient.calories = round(float(nutrition.calories), 2)
    ingredient.protein = round(float(nutrition.protein), 2)
    ingredient.carbs = round(float(nutrition.carbs), 2)
    ingredient.fats = round(float(nutrition.fats), 2)

    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    return ingredient


def _update_ingredient_from_macros(
    ingredient: models.Ingredient,
    macros: dict,
    db: Session,
) -> models.Ingredient:
    ingredient.calories = round(float(macros["calories"]), 2)
    ingredient.protein = round(float(macros["protein"]), 2)
    ingredient.carbs = round(float(macros["carbs"]), 2)
    ingredient.fats = round(float(macros["fats"]), 2)

    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    return ingredient


async def _estimate_with_fdc_then_ai(
    ingredient: models.Ingredient,
    estimator,
    db: Session,
) -> models.Ingredient:
    macros = await _lookup_fdc_macros(ingredient)
    if macros:
        logger.info("Ingredient %s matched via FDC", ingredient.id)
        return _update_ingredient_from_macros(ingredient, macros, db)

    logger.info("Ingredient %s falling back to AI estimation", ingredient.id)
    return await _estimate_and_update_ingredient(ingredient, estimator, db)


async def _lookup_fdc_macros(ingredient: models.Ingredient) -> dict | None:
    lookup_name = ingredient.name
    allow_ascii = False
    try:
        translator = get_ingredient_translator()
    except ValueError as exc:
        logger.warning(
            "Ingredient translation unavailable for ingredient %s: %s", ingredient.id, exc
        )
    else:
        try:
            translated = await translator.translate_to_english(ingredient.name)
            if translated:
                lookup_name = translated
                allow_ascii = True
        except IngredientTranslationError as exc:
            logger.warning(
                "Ingredient translation failed for ingredient %s: %s", ingredient.id, exc.message
            )
        except Exception as exc:
            logger.warning(
                "Ingredient translation failed for ingredient %s: %s", ingredient.id, exc
            )

    try:
        normalized_unit = normalize_unit(ingredient.base_unit) or ingredient.base_unit
        return fdc_lookup.lookup_nutrition(
            lookup_name,
            normalized_unit,
            allow_ascii=allow_ascii,
        )
    except fdc_lookup.FdcLookupError as exc:
        logger.warning("FDC lookup unavailable for ingredient %s: %s", ingredient.id, exc)
        return None


@router.get("/", response_model=list[schemas.Ingredient])
async def list_ingredients(db: Session = Depends(get_db), name: str | None = Query(default=None)):
    db_query = db.query(models.Ingredient).order_by(models.Ingredient.name)
    if name:
        name = unquote(name)
        db_query = db_query.filter(models.Ingredient.name.ilike(f"%{name}%"))
    return db_query.all()


@router.post("/", response_model=schemas.Ingredient)
async def create_ingredient(
    ingredient: schemas.IngredientCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Check if user provided NO nutrition at all (all fields are None)
    # If they provide partial data, we assume intentional (e.g., salt has 0 calories)
    nutrition_fields = ("calories", "protein", "carbs", "fats")
    all_nutrition_none = all(getattr(ingredient, field) is None for field in nutrition_fields)

    # Convert None nutrition values to 0 for database storage
    ingredient_data = ingredient.model_dump(mode="json")
    for field in nutrition_fields:
        if ingredient_data.get(field) is None:
            ingredient_data[field] = 0.0

    db_ingredient = models.Ingredient(**ingredient_data)
    db.add(db_ingredient)
    db.commit()
    db.refresh(db_ingredient)

    # Only estimate if user provided NO nutrition data at all
    # This distinguishes "unknown" from intentional zero-calorie items like salt/water
    if all_nutrition_none:
        background_tasks.add_task(_estimate_nutrition_background_sync, db_ingredient.id)
        logger.info(
            "Ingredient %s created without nutrition, scheduling background estimation",
            db_ingredient.id,
        )

    return db_ingredient


@router.post("/{ingredient_id}/estimate-nutrition", response_model=schemas.Ingredient)
async def estimate_ingredient_nutrition(
    ingredient_id: int,
    db: Session = Depends(get_db),
):
    """
    Estimate nutrition for a single ingredient (per 100 base_unit) using FDC first, AI fallback.
    """
    ingredient = db.query(models.Ingredient).filter(models.Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    try:
        macros = await _lookup_fdc_macros(ingredient)
        if macros:
            return _update_ingredient_from_macros(ingredient, macros, db)

        # FDC failed or no match; use AI
        try:
            estimator = get_nutrition_estimator()
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

        updated = await _estimate_and_update_ingredient(ingredient, estimator, db)
        return updated
    except NutritionEstimationError as e:
        db.rollback()
        if e.is_rate_limited:
            raise HTTPException(status_code=429, detail=e.message) from e
        if "environment variable is not set" in e.message or "API key not configured" in e.message:
            raise HTTPException(status_code=503, detail=e.message) from e
        raise HTTPException(status_code=500, detail=e.message) from e


@router.post("/estimate-missing", response_model=schemas.IngredientBulkEstimateResponse)
async def estimate_missing_ingredients(
    db: Session = Depends(get_db),
):
    """
    Estimate nutrition for all ingredients where all nutrition fields are zero or null.
    Processes sequentially to avoid rate limits, using FDC first then AI fallback.
    """
    total_count = db.query(func.count(models.Ingredient.id)).scalar() or 0
    missing = (
        db.query(models.Ingredient)
        .filter(
            func.coalesce(models.Ingredient.calories, 0) == 0,
            func.coalesce(models.Ingredient.protein, 0) == 0,
            func.coalesce(models.Ingredient.carbs, 0) == 0,
            func.coalesce(models.Ingredient.fats, 0) == 0,
        )
        .order_by(models.Ingredient.id)
        .all()
    )
    estimator = None
    updated: list[models.Ingredient] = []
    failed: list[schemas.IngredientNutritionEstimateFailure] = []
    skipped_count = total_count - len(missing)

    for ingredient in missing:
        try:
            macros = await _lookup_fdc_macros(ingredient)
            if macros:
                logger.info("Ingredient %s matched via FDC", ingredient.id)
                updated_ing = _update_ingredient_from_macros(ingredient, macros, db)
                updated.append(updated_ing)
                continue

            # FDC missing/unavailable -> AI fallback
            try:
                if estimator is None:
                    estimator = get_nutrition_estimator()
            except ValueError as e:
                failed.append(
                    schemas.IngredientNutritionEstimateFailure(
                        id=ingredient.id,
                        reason=str(e),
                        rate_limited=False,
                    )
                )
                continue

            updated_ing = await _estimate_and_update_ingredient(ingredient, estimator, db)
            updated.append(updated_ing)
        except NutritionEstimationError as e:
            db.rollback()
            # Retry once on rate limit with a short backoff
            if e.is_rate_limited:
                await asyncio.sleep(1.0)
                try:
                    updated_ing = await _estimate_and_update_ingredient(ingredient, estimator, db)
                    updated.append(updated_ing)
                    continue
                except NutritionEstimationError as retry_err:
                    db.rollback()
                    failed.append(
                        schemas.IngredientNutritionEstimateFailure(
                            id=ingredient.id,
                            reason=retry_err.message,
                            rate_limited=retry_err.is_rate_limited,
                        )
                    )
                    continue

            failed.append(
                schemas.IngredientNutritionEstimateFailure(
                    id=ingredient.id,
                    reason=e.message,
                    rate_limited=e.is_rate_limited,
                )
            )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            db.rollback()
            failed.append(
                schemas.IngredientNutritionEstimateFailure(
                    id=ingredient.id,
                    reason=str(e),
                    rate_limited=False,
                )
            )

    return schemas.IngredientBulkEstimateResponse(
        updated=updated,
        updated_count=len(updated),
        skipped_count=skipped_count,
        failed=failed,
    )


def do_merge(keep_ingredient_id: int, merge_ingredient_ids: list[int], db: Session):
    # Validate that keep_ingredient exists
    keep_ingredient = (
        db.query(models.Ingredient).filter(models.Ingredient.id == keep_ingredient_id).first()
    )

    if not keep_ingredient:
        raise HTTPException(status_code=404, detail="Keep ingredient not found")

    # Validate that all merge ingredients exist
    merge_ingredients = (
        db.query(models.Ingredient).filter(models.Ingredient.id.in_(merge_ingredient_ids)).all()
    )

    if len(merge_ingredients) != len(merge_ingredient_ids):
        raise HTTPException(status_code=404, detail="One or more merge ingredients not found")

    # Ensure keep_ingredient is not in merge list
    if keep_ingredient_id in merge_ingredient_ids:
        raise HTTPException(status_code=400, detail="Keep ingredient cannot be in the merge list")

    # Update all RecipeIngredient entries to use the kept ingredient
    db.query(models.RecipeIngredient).filter(
        models.RecipeIngredient.ingredient_id.in_(merge_ingredient_ids)
    ).update({models.RecipeIngredient.ingredient_id: keep_ingredient_id}, synchronize_session=False)

    # Update all ShoppingListItem entries to use the kept ingredient
    db.query(models.ShoppingListItem).filter(
        models.ShoppingListItem.ingredient_id.in_(merge_ingredient_ids)
    ).update({models.ShoppingListItem.ingredient_id: keep_ingredient_id}, synchronize_session=False)

    # Delete the merged ingredients
    db.query(models.Ingredient).filter(models.Ingredient.id.in_(merge_ingredient_ids)).delete(
        synchronize_session=False
    )

    db.commit()
    return keep_ingredient


@router.post("/merge")
async def merge_ingredients(
    keep_ingredient_id: int, merge_ingredient_ids: list[int], db: Session = Depends(get_db)
):
    """
    Merge duplicate ingredients into a single ingredient.
    All recipes using the merged ingredients will be updated to use the kept ingredient.

    Args:
        keep_ingredient_id: ID of the ingredient to keep
        merge_ingredient_ids: List of ingredient IDs to merge into the kept ingredient
    """
    try:
        keep_ingredient = do_merge(keep_ingredient_id, merge_ingredient_ids, db)
    except Exception:
        db.rollback()
        raise

    return {
        "message": f"Successfully merged {len(merge_ingredient_ids)} ingredients into '{keep_ingredient.name}'",
        "kept_ingredient": {
            "id": keep_ingredient_id,
        },
        "merged_count": len(merge_ingredient_ids),
    }
