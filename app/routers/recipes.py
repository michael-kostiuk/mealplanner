from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from ..database import get_db
from .. import models, schemas
import json
from datetime import datetime

router = APIRouter(
    prefix="/recipes",
    tags=["recipes"]
)

@router.get("/", response_model=List[schemas.Recipe])
async def list_recipes(
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = None,
    name: Optional[str] = None,
    dietary_tags: Optional[List[str]] = Query(None),
    max_prep_time: Optional[int] = None,
    min_calories: Optional[int] = None,
    max_calories: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Recipe)
    
    if name:
        query = query.filter(models.Recipe.name.ilike(f"%{name}%"))
    if category:
        query = query.filter(models.Recipe.category == category)
    if dietary_tags:
        query = query.filter(models.Recipe.dietary_tags.contains(dietary_tags))
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
        image_url=recipe.image_url
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)
    
    # Add ingredients
    for ingredient_data in recipe.ingredients:
        db_recipe_ingredient = models.RecipeIngredient(
            recipe_id=db_recipe.id,
            **ingredient_data.model_dump()
        )
        db.add(db_recipe_ingredient)
    
    db.commit()
    db.refresh(db_recipe)
    return db_recipe

@router.post("/bulk-import", response_model=List[schemas.Recipe])
async def bulk_import_recipes(recipes: List[schemas.RecipeCreate], db: Session = Depends(get_db)):
    imported_recipes = []
    for recipe_data in recipes:
        # Filter out fields that don't exist in the model
        recipe_dict = recipe_data.model_dump(exclude={'ingredients'})
        # Remove dietary_tags if it's not in the model
        if 'dietary_tags' in recipe_dict:
            del recipe_dict['dietary_tags']
        db_recipe = models.Recipe(**recipe_dict)
        db.add(db_recipe)
        db.commit()
        db.refresh(db_recipe)
        
        for ingredient_data in recipe_data.ingredients:
            db_recipe_ingredient = models.RecipeIngredient(
                recipe_id=db_recipe.id,
                **ingredient_data.model_dump()
            )
            db.add(db_recipe_ingredient)
        
        imported_recipes.append(db_recipe)
    
    db.commit()
    return imported_recipes

@router.get("/{recipe_id}", response_model=schemas.Recipe)
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe

@router.put("/{recipe_id}", response_model=schemas.Recipe)
async def update_recipe(recipe_id: int, recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    db_recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if db_recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    old_image_url = db_recipe.image_url
    new_image_url = recipe.image_url
    
    # Delete old image if it's being replaced
    if old_image_url and new_image_url and old_image_url != new_image_url:
        from ..services.dropbox_service import dropbox_service
        try:
            await dropbox_service.delete_image(old_image_url)
        except Exception as e:
            print(f"Warning: Could not delete old image: {e}")
    
    # Update recipe attributes
    for key, value in recipe.model_dump(exclude={'ingredients'}).items():
        setattr(db_recipe, key, value)
    
    # Update ingredients
    db.query(models.RecipeIngredient).filter(models.RecipeIngredient.recipe_id == recipe_id).delete()
    
    for ingredient_data in recipe.ingredients:
        db_recipe_ingredient = models.RecipeIngredient(
            recipe_id=recipe_id,
            **ingredient_data.model_dump()
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
    
    # Delete associated recipe ingredients (cascade will handle this if set up in models)
    db.delete(db_recipe)
    db.commit()
    return {"message": "Recipe deleted successfully"}

@router.post("/{recipe_id}/upload-image")
async def upload_recipe_image(
    recipe_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        print(f"[UPLOAD] Upload image request for recipe {recipe_id}")
        print(f"[UPLOAD] File info - filename: {file.filename}, content_type: {file.content_type}")
        
        recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
        if not recipe:
            print(f"[UPLOAD] ERROR: Recipe {recipe_id} not found")
            raise HTTPException(status_code=404, detail="Recipe not found")
        
        # Validate file type
        if not file.content_type or not file.content_type.startswith("image/"):
            print(f"[UPLOAD] ERROR: Invalid file type {file.content_type}")
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Read file data
        file_data = await file.read()
        print(f"[UPLOAD] File data size: {len(file_data)} bytes")
        # Note: MAX_FILE_SIZE (10MB) is also defined in frontend/src/constants.ts
        if len(file_data) > 10 * 1024 * 1024:  # 10MB limit
            print(f"[UPLOAD] ERROR: File too large: {len(file_data)} bytes")
            raise HTTPException(status_code=400, detail="File too large (max 10MB)")
        
        # Generate filename
        import time
        timestamp = int(time.time())
        filename = f"{recipe_id}_{timestamp}_{file.filename}"
        print(f"[UPLOAD] Generated filename: {filename}")
        
        # Upload to Dropbox
        from ..services.dropbox_service import dropbox_service
        print("[UPLOAD] Calling Dropbox service...")
        image_url = await dropbox_service.upload_image(file_data, filename)
        
        if not image_url:
            print("[UPLOAD] ERROR: Dropbox returned None")
            raise HTTPException(status_code=500, detail="Failed to upload image to Dropbox")
        
        # Update recipe
        recipe.image_url = image_url
        db.commit()
        print(f"[UPLOAD] SUCCESS: Recipe updated with image_url: {image_url}")
        
        return {"image_url": image_url}
    except ValueError as e:
        # Handle Dropbox-specific errors
        error_msg = str(e)
        print(f"[UPLOAD] Dropbox Error: {error_msg}")
        if "expired" in error_msg.lower() or "invalid" in error_msg.lower():
            raise HTTPException(
                status_code=401,
                detail="Dropbox access token is expired or invalid. Please regenerate the token in Dropbox Developer Console."
            )
        raise HTTPException(status_code=500, detail=error_msg)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[UPLOAD] ERROR in upload_recipe_image: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/export", response_model=List[schemas.Recipe])
async def export_recipes(db: Session = Depends(get_db)):
    recipes = db.query(models.Recipe).all()
    return recipes

@router.get("/search", response_model=List[schemas.Recipe])
async def search_recipes(
    query: str,
    category: Optional[str] = None,
    dietary_tags: Optional[List[str]] = Query(None),
    max_prep_time: Optional[int] = None,
    min_calories: Optional[int] = None,
    max_calories: Optional[int] = None,
    db: Session = Depends(get_db)
):
    search = f"%{query}%"
    db_query = db.query(models.Recipe).filter(
        or_(
            models.Recipe.name.ilike(search),
            models.Recipe.instructions.ilike(search),
            models.Recipe.category.ilike(search)
        )
    )
    
    if category:
        db_query = db_query.filter(models.Recipe.category == category)
    if dietary_tags:
        db_query = db_query.filter(models.Recipe.dietary_tags.contains(dietary_tags))
    if max_prep_time:
        db_query = db_query.filter(models.Recipe.prep_time <= max_prep_time)
    if min_calories:
        db_query = db_query.filter(models.Recipe.calories >= min_calories)
    if max_calories:
        db_query = db_query.filter(models.Recipe.calories <= max_calories)
    
    return db_query.all()