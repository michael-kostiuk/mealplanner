from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from .. import models, schemas
from urllib.parse import unquote

router = APIRouter(
    prefix="/ingredients",
    tags=["ingredients"],
)

@router.get("/", response_model=List[schemas.Ingredient])
async def list_ingredients(db: Session = Depends(get_db), name: Optional[str] = Query(default=None)):
    db_query = db.query(models.Ingredient)
    if name:
        name = unquote(name)
        db_query = db_query.filter(models.Ingredient.name.ilike(f"%{name}%"))
    return db_query.all()

@router.post("/", response_model=schemas.Ingredient)
async def create_ingredient(ingredient: schemas.IngredientCreate, db: Session = Depends(get_db)):
    db_ingredient = models.Ingredient(**ingredient.model_dump())
    db.add(db_ingredient)
    db.commit()
    db.refresh(db_ingredient)
    return db_ingredient


@router.post("/merge")
async def merge_ingredients(
    keep_ingredient_id: int,
    merge_ingredient_ids: List[int],
    db: Session = Depends(get_db)
):
    """
    Merge duplicate ingredients into a single ingredient.
    All recipes using the merged ingredients will be updated to use the kept ingredient.
    
    Args:
        keep_ingredient_id: ID of the ingredient to keep
        merge_ingredient_ids: List of ingredient IDs to merge into the kept ingredient
    """
    
    # Validate that keep_ingredient exists
    keep_ingredient = db.query(models.Ingredient).filter(
        models.Ingredient.id == keep_ingredient_id
    ).first()
    
    if not keep_ingredient:
        raise HTTPException(status_code=404, detail="Keep ingredient not found")
    
    # Validate that all merge ingredients exist
    merge_ingredients = db.query(models.Ingredient).filter(
        models.Ingredient.id.in_(merge_ingredient_ids)
    ).all()
    
    if len(merge_ingredients) != len(merge_ingredient_ids):
        raise HTTPException(status_code=404, detail="One or more merge ingredients not found")
    
    # Ensure keep_ingredient is not in merge list
    if keep_ingredient_id in merge_ingredient_ids:
        raise HTTPException(
            status_code=400, 
            detail="Keep ingredient cannot be in the merge list"
        )
    
    try:
        # Update all RecipeIngredient entries to use the kept ingredient
        db.query(models.RecipeIngredient).filter(
            models.RecipeIngredient.ingredient_id.in_(merge_ingredient_ids)
        ).update({
            models.RecipeIngredient.ingredient_id: keep_ingredient_id
        }, synchronize_session=False)
        
        # Update all ShoppingListItem entries to use the kept ingredient
        db.query(models.ShoppingListItem).filter(
            models.ShoppingListItem.ingredient_id.in_(merge_ingredient_ids)
        ).update({
            models.ShoppingListItem.ingredient_id: keep_ingredient_id
        }, synchronize_session=False)
        
        # Delete the merged ingredients
        db.query(models.Ingredient).filter(
            models.Ingredient.id.in_(merge_ingredient_ids)
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return {
            "message": f"Successfully merged {len(merge_ingredient_ids)} ingredients into '{keep_ingredient.name}'",
            "kept_ingredient": {
                "id": keep_ingredient.id,
                "name": keep_ingredient.name
            },
            "merged_count": len(merge_ingredient_ids)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error merging ingredients: {str(e)}")