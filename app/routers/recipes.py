from fastapi import APIRouter, Depends, HTTPException, Query
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
        dietary_tags=recipe.dietary_tags,
        calories=recipe.calories,
        protein=recipe.protein,
        carbs=recipe.carbs,
        fats=recipe.fats,
        breakfast_weight=recipe.breakfast_weight,
        lunch_weight=recipe.lunch_weight,
        dinner_weight=recipe.dinner_weight
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
    
    # Delete associated recipe ingredients (cascade will handle this if set up in models)
    db.delete(db_recipe)
    db.commit()
    return {"message": "Recipe deleted successfully"}

@router.post("/bulk-import", response_model=List[schemas.Recipe])
async def bulk_import_recipes(recipes: List[schemas.RecipeCreate], db: Session = Depends(get_db)):
    imported_recipes = []
    for recipe_data in recipes:
        db_recipe = models.Recipe(**recipe_data.model_dump(exclude={'ingredients'}))
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