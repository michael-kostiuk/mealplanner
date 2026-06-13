import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/favorites", tags=["favorites"])


def get_user(db: Session = Depends(get_db)):
    """Get the current user (hardcoded to user_id=1 for demo)."""
    usr = db.query(models.User).filter(models.User.id == 1).first()
    if not usr:
        usr = models.User(id=1, email="test@example.com")
        db.add(usr)
        db.commit()
        db.refresh(usr)
    return usr


@router.get("/", response_model=list[schemas.Favorite])
async def list_favorites(db: Session = Depends(get_db), user: models.User = Depends(get_user)):
    """List all favorites for the current user."""
    favorites = (
        db.query(models.Favorite)
        .options(
            joinedload(models.Favorite.recipe)
            .joinedload(models.Recipe.ingredients)
            .joinedload(models.RecipeIngredient.ingredient)
        )
        .filter(models.Favorite.user_id == user.id)
        .all()
    )
    return favorites


@router.post("/", response_model=schemas.Favorite, status_code=201)
async def add_favorite(
    favorite: schemas.FavoriteCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_user),
):
    """Add a recipe to favorites."""
    # Check if recipe exists
    recipe = db.query(models.Recipe).filter(models.Recipe.id == favorite.recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    # Check if already favorited
    existing = (
        db.query(models.Favorite)
        .filter(models.Favorite.user_id == user.id, models.Favorite.recipe_id == favorite.recipe_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Recipe already in favorites")

    db_favorite = models.Favorite(user_id=user.id, recipe_id=favorite.recipe_id)
    db.add(db_favorite)
    db.commit()
    db.refresh(db_favorite)
    return db_favorite


@router.delete("/recipe/{recipe_id}")
async def remove_favorite(
    recipe_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_user)
):
    """Remove a recipe from favorites by recipe ID."""
    favorite = (
        db.query(models.Favorite)
        .filter(models.Favorite.user_id == user.id, models.Favorite.recipe_id == recipe_id)
        .first()
    )
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    db.delete(favorite)
    db.commit()
    return {"message": "Favorite removed successfully"}


@router.get("/recipe/{recipe_id}", response_model=dict)
async def check_favorite(
    recipe_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_user)
):
    """Check if a recipe is in the user's favorites."""
    favorite = (
        db.query(models.Favorite)
        .filter(models.Favorite.user_id == user.id, models.Favorite.recipe_id == recipe_id)
        .first()
    )
    return {"favorite": favorite is not None}
