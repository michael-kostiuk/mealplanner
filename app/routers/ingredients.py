from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from .. import models, schemas

router = APIRouter(
    prefix="/ingredients",
    tags=["ingredients"]
)

@router.get("/", response_model=List[schemas.Ingredient])
async def list_ingredients(db: Session = Depends(get_db)):
    return db.query(models.Ingredient).all()

@router.post("/", response_model=schemas.Ingredient)
async def create_ingredient(ingredient: schemas.IngredientCreate, db: Session = Depends(get_db)):
    db_ingredient = models.Ingredient(**ingredient.model_dump())
    db.add(db_ingredient)
    db.commit()
    db.refresh(db_ingredient)
    return db_ingredient