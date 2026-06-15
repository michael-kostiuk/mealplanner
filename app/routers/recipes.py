import logging
import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services.recipe_from_image import recipe_from_image_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.post("/parse-from-image", response_model=schemas.RecipeFromImageStartResponse)
async def parse_recipe_from_image(
    file: UploadFile = File(...),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    file_data = await file.read()
    if len(file_data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    return await recipe_from_image_service.start_job(file_data, file.content_type)


@router.get("/parse-from-image/{job_id}", response_model=schemas.RecipeFromImageJob)
async def get_parse_from_image_job(job_id: str):
    job = await recipe_from_image_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/parse-from-image/{job_id}/cancel")
async def cancel_parse_from_image_job(job_id: str):
    ok = await recipe_from_image_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "canceled"}


@router.get("/", response_model=list[schemas.Recipe])
async def list_recipes(
    skip: int = 0,
    limit: int = 100,
    category: str | None = None,
    name: str | None = None,
    max_prep_time: int | None = None,
    min_calories: int | None = None,
    max_calories: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Recipe)

    if name:
        query = query.filter(models.Recipe.name.ilike(f"%{name}%"))
    if category:
        query = query.filter(models.Recipe.category == category)
    if max_prep_time:
        query = query.filter(models.Recipe.prep_time <= max_prep_time)
    if min_calories:
        query = query.filter(models.Recipe.calories >= min_calories)
    if max_calories:
        query = query.filter(models.Recipe.calories <= max_calories)

    return query.offset(skip).limit(limit).all()


@router.post("/", response_model=schemas.Recipe)
async def create_recipe(recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    db_recipe = models.Recipe(
        name=recipe.name,
        servings=recipe.servings,
        prep_time=recipe.prep_time,
        cook_time=recipe.cook_time,
        instructions=recipe.instructions,
        category=recipe.category,
        calories=recipe.calories,
        protein=recipe.protein,
        carbs=recipe.carbs,
        fats=recipe.fats,
        breakfast_weight=recipe.breakfast_weight,
        lunch_weight=recipe.lunch_weight,
        dinner_weight=recipe.dinner_weight,
        image_url=recipe.image_url,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)

    # Add ingredients
    for ingredient_data in recipe.ingredients:
        db_recipe_ingredient = models.RecipeIngredient(
            recipe_id=db_recipe.id, **ingredient_data.model_dump()
        )
        db.add(db_recipe_ingredient)

    db.commit()
    db.refresh(db_recipe)
    return db_recipe


@router.post("/bulk-import", response_model=list[schemas.Recipe])
async def bulk_import_recipes(recipes: list[schemas.RecipeCreate], db: Session = Depends(get_db)):
    imported_recipes = []
    for recipe_data in recipes:
        recipe_dict = recipe_data.model_dump(exclude={"ingredients"})
        db_recipe = models.Recipe(**recipe_dict)
        db.add(db_recipe)
        # Known limitation: one commit per recipe to get the id for ingredients.
        # A single transaction with flush() would be more efficient.
        db.commit()
        db.refresh(db_recipe)

        for ingredient_data in recipe_data.ingredients:
            db_recipe_ingredient = models.RecipeIngredient(
                recipe_id=db_recipe.id, **ingredient_data.model_dump()
            )
            db.add(db_recipe_ingredient)

        imported_recipes.append(db_recipe)

    db.commit()
    return imported_recipes


@router.get("/suggestions", response_model=list[schemas.Recipe])
async def get_recipe_suggestions(
    meal_type: str,
    exclude_ids: list[int] | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Get recipe suggestions for a specific meal type, ordered by suitability weight.

    - meal_type: "breakfast", "lunch", or "dinner"
    - exclude_ids: Recipe IDs to exclude (e.g., already used in the meal plan for that day)
    - limit: Maximum number of suggestions to return (1-100)
    """
    if meal_type not in ("breakfast", "lunch", "dinner"):
        raise HTTPException(
            status_code=400,
            detail="meal_type must be 'breakfast', 'lunch', or 'dinner'",
        )

    # Normalize exclude_ids
    exclude_ids = exclude_ids or []

    weight_attr = getattr(models.Recipe, f"{meal_type}_weight")

    query = db.query(models.Recipe).filter(weight_attr > 0)

    if exclude_ids:
        query = query.filter(models.Recipe.id.notin_(exclude_ids))

    query = query.order_by(weight_attr.desc())

    return query.limit(limit).all()


@router.get("/{recipe_id}", response_model=schemas.Recipe)
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@router.put("/{recipe_id}", response_model=schemas.Recipe)
async def update_recipe(
    recipe_id: int, recipe: schemas.RecipeCreate, db: Session = Depends(get_db)
):
    db_recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    old_image_url = db_recipe.image_url
    new_image_url = recipe.image_url

    # Delete old image if it's being replaced or removed
    if old_image_url and (new_image_url is None or old_image_url != new_image_url):
        from ..services.dropbox_service import dropbox_service

        try:
            await dropbox_service.delete_image(old_image_url)
        except Exception as e:
            # Silent failure - recipe update should succeed even if old image deletion fails
            # Old images are not critical and can be cleaned up manually if needed
            logger.warning(f"Could not delete old image: {e}", exc_info=True)

    # Update recipe attributes
    for key, value in recipe.model_dump(exclude={"ingredients"}).items():
        setattr(db_recipe, key, value)

    # Update ingredients
    db.query(models.RecipeIngredient).filter(
        models.RecipeIngredient.recipe_id == recipe_id
    ).delete()

    for ingredient_data in recipe.ingredients:
        db_recipe_ingredient = models.RecipeIngredient(
            recipe_id=recipe_id, **ingredient_data.model_dump()
        )
        db.add(db_recipe_ingredient)

    db.commit()
    db.refresh(db_recipe)
    return db_recipe


@router.delete("/{recipe_id}")
async def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    db_recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Delete image from Dropbox if exists
    image_url = db_recipe.image_url
    if image_url:
        from ..services.dropbox_service import dropbox_service

        await dropbox_service.delete_image(image_url)

    db.delete(db_recipe)
    db.commit()
    return {"message": "Recipe deleted successfully"}


@router.post("/{recipe_id}/upload-image")
async def upload_recipe_image(
    recipe_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    logger.info(f"Upload image request for recipe {recipe_id}")
    logger.info(f"File info - filename: {file.filename}, content_type: {file.content_type}")

    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if not recipe:
        logger.error(f"Recipe {recipe_id} not found")
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        logger.error(f"Invalid file type {file.content_type}")
        raise HTTPException(status_code=400, detail="File must be an image")

    # Read file data
    file_data = await file.read()
    logger.info(f"File data size: {len(file_data)} bytes")
    # Note: MAX_FILE_SIZE (10MB) is also defined in frontend/src/constants.ts
    if len(file_data) > 10 * 1024 * 1024:  # 10MB limit
        logger.error(f"File too large: {len(file_data)} bytes")
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # Generate filename
    timestamp = int(time.time())
    filename = f"{recipe_id}_{timestamp}_{file.filename}"
    logger.info(f"Generated filename: {filename}")

    # Upload to Dropbox
    from ..services.dropbox_service import dropbox_service

    logger.info("Calling Dropbox service...")
    image_url = await dropbox_service.upload_image(file_data, filename)

    if not image_url:
        logger.error("Dropbox returned None")
        raise HTTPException(status_code=500, detail="Failed to upload image to Dropbox")

    # Update recipe
    recipe.image_url = image_url
    db.commit()
    logger.info(f"SUCCESS: Recipe updated with image_url: {image_url}")

    return {"image_url": image_url}


@router.get("/export", response_model=list[schemas.Recipe])
async def export_recipes(db: Session = Depends(get_db)):
    recipes = db.query(models.Recipe).all()
    return recipes


@router.get("/search", response_model=list[schemas.Recipe])
async def search_recipes(
    query: str,
    category: str | None = None,
    max_prep_time: int | None = None,
    min_calories: int | None = None,
    max_calories: int | None = None,
    db: Session = Depends(get_db),
):
    search = f"%{query}%"
    db_query = db.query(models.Recipe).filter(
        or_(
            models.Recipe.name.ilike(search),
            models.Recipe.instructions.ilike(search),
            models.Recipe.category.ilike(search),
        )
    )

    if category:
        db_query = db_query.filter(models.Recipe.category == category)
    if max_prep_time:
        db_query = db_query.filter(models.Recipe.prep_time <= max_prep_time)
    if min_calories:
        db_query = db_query.filter(models.Recipe.calories >= min_calories)
    if max_calories:
        db_query = db_query.filter(models.Recipe.calories <= max_calories)

    return db_query.all()
