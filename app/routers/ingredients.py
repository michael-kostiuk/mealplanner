from fastapi import APIRouter, Depends, HTTPException
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
async def list_ingredients(db: Session = Depends(get_db), name: Optional[str] = Query()):
    db_query =  db.query(models.Ingredient).all()
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