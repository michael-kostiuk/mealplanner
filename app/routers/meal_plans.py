import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.current_user import get_current_user
from ..database import get_db
from ..services import MealPlanGenerator
from .shopping_lists import generate_shopping_list

logger = logging.getLogger(__name__)


def _entry_fields(entry: schemas.MealPlanEntryCreate, previous: dict) -> dict:
    """Entry columns from a request. Clients that don't send `is_leftover` keep the flag of
    the previous entry with the same day, meal type and recipe; a new recipe is cooked."""
    data = entry.model_dump()
    if data["is_leftover"] is None:
        key = (entry.date.date(), entry.meal_type, entry.recipe_id)
        data["is_leftover"] = previous.get(key, False)
    return data


def _leftover_flags(entries: list[models.MealPlanEntry]) -> dict:
    return {(e.date.date(), e.meal_type, e.recipe_id): e.is_leftover for e in entries}


router = APIRouter(prefix="/meal-plans", tags=["meal-plans"])


def _get_owned_plan(db: Session, meal_plan_id: int, user: models.User) -> models.MealPlan:
    """The plan, or 404 when it doesn't exist or belongs to someone else."""
    plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    return plan


@router.get("/", response_model=list[schemas.MealPlan])
async def list_meal_plans(
    db: Annotated[Session, Depends(get_db)], user: Annotated[models.User, Depends(get_current_user)]
):
    return db.query(models.MealPlan).filter(models.MealPlan.user_id == user.id).all()


@router.post("/", response_model=schemas.MealPlan)
async def create_meal_plan(
    meal_plan: schemas.MealPlanCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    db_meal_plan = models.MealPlan(
        user_id=user.id,
        start_date=meal_plan.start_date,
        end_date=meal_plan.end_date,
        people_count=meal_plan.people_count,
        target_calories=meal_plan.target_calories,
        dietary_preferences=meal_plan.dietary_preferences,
    )
    db.add(db_meal_plan)
    db.commit()
    db.refresh(db_meal_plan)

    # Create meal plan entries
    for entry in meal_plan.entries:
        db_entry = models.MealPlanEntry(meal_plan_id=db_meal_plan.id, **_entry_fields(entry, {}))
        db.add(db_entry)

    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan


@router.post("/auto-generate", response_model=schemas.MealPlan)
async def auto_generate_meal_plan(
    start_date: datetime | None = None,
    days: int | None = None,
    target_calories: int | None = None,
    people_count: int | None = None,
    dietary_preferences: list[str] = Query([]),
    meal_plan_id: int | None = Query(None, alias="id"),
    *,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    # Get all available recipes
    if db.query(models.Recipe.id).first() is None:
        raise HTTPException(status_code=400, detail="No recipes available for meal planning")

    planner = MealPlanGenerator(db)
    if meal_plan_id is not None:
        meal_plan = _get_owned_plan(db, meal_plan_id, user)
        try:
            db_meal_plan = planner.regenerate_meal_plan(meal_plan)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        db.refresh(db_meal_plan)
        return db_meal_plan

    missing_params = [
        name
        for name, value in {
            "start_date": start_date,
            "days": days,
            "target_calories": target_calories,
            "people_count": people_count,
        }.items()
        if value is None
    ]
    if missing_params:
        raise HTTPException(
            status_code=400, detail=f"Missing required params: {', '.join(missing_params)}"
        )

    # Create meal plan
    try:
        db_meal_plan = planner.generate_meal_plan(
            start_date=start_date,
            days=days,
            target_calories=target_calories,
            people_count=people_count,
            dietary_preferences=dietary_preferences,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan


@router.post("/suggest-meal", response_model=schemas.Recipe)
async def suggest_meal(req: schemas.MealSuggestRequest, db: Annotated[Session, Depends(get_db)]):
    """Suggest one replacement recipe for a single meal slot (the re-roll action)."""
    if db.query(models.Recipe.id).first() is None:
        raise HTTPException(status_code=400, detail="No recipes available for meal planning")

    planner = MealPlanGenerator(db)
    try:
        recipe = planner.suggest_meal(
            meal_type=req.meal_type,
            target_calories=req.target_calories,
            plan_recipe_ids=req.plan_recipe_ids,
            current_recipe_id=req.current_recipe_id,
            exclude_recipe_ids=req.exclude_recipe_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return recipe


@router.get("/{meal_plan_id}", response_model=schemas.MealPlan)
async def get_meal_plan(
    meal_plan_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    return _get_owned_plan(db, meal_plan_id, user)


@router.put("/{meal_plan_id}", response_model=schemas.MealPlan)
async def update_meal_plan(
    meal_plan_id: int,
    meal_plan: schemas.MealPlanCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    db_meal_plan = _get_owned_plan(db, meal_plan_id, user)

    # Update meal plan attributes
    for key, value in meal_plan.model_dump(exclude={"entries"}).items():
        setattr(db_meal_plan, key, value)

    # Update entries
    previous = _leftover_flags(db_meal_plan.entries)
    db.query(models.MealPlanEntry).filter(
        models.MealPlanEntry.meal_plan_id == meal_plan_id
    ).delete()

    for entry in meal_plan.entries:
        db_entry = models.MealPlanEntry(meal_plan_id=meal_plan_id, **_entry_fields(entry, previous))
        db.add(db_entry)

    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan


@router.delete("/{meal_plan_id}")
async def delete_meal_plan(
    meal_plan_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    db_meal_plan = _get_owned_plan(db, meal_plan_id, user)

    db.delete(db_meal_plan)
    db.commit()
    return {"message": "Meal plan deleted successfully"}


@router.put("/{meal_plan_id}/meals/{meal_id}", response_model=schemas.MealPlanEntry)
async def update_meal(
    meal_plan_id: int,
    meal_id: int,
    meal: schemas.MealPlanEntryCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    _get_owned_plan(db, meal_plan_id, user)
    db_meal = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.id == meal_id, models.MealPlanEntry.meal_plan_id == meal_plan_id
        )
        .first()
    )

    if db_meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    for key, value in _entry_fields(meal, _leftover_flags([db_meal])).items():
        setattr(db_meal, key, value)

    db.commit()
    db.refresh(db_meal)
    return db_meal


@router.post("/{meal_plan_id}/meals", response_model=schemas.MealPlanEntry)
async def add_meal(
    meal_plan_id: int,
    meal: schemas.MealPlanEntryCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    """Add a new meal to a meal plan."""
    _get_owned_plan(db, meal_plan_id, user)

    # Verify recipe exists
    recipe = db.query(models.Recipe).filter(models.Recipe.id == meal.recipe_id).first()
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    db_meal = models.MealPlanEntry(meal_plan_id=meal_plan_id, **_entry_fields(meal, {}))
    db.add(db_meal)
    db.commit()
    db.refresh(db_meal)
    return db_meal


@router.delete("/{meal_plan_id}/meals/{meal_id}")
async def delete_meal(
    meal_plan_id: int,
    meal_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    """Remove a meal from a meal plan."""
    _get_owned_plan(db, meal_plan_id, user)
    db_meal = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.id == meal_id, models.MealPlanEntry.meal_plan_id == meal_plan_id
        )
        .first()
    )

    if db_meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    db.delete(db_meal)
    db.commit()
    return {"message": "Meal deleted successfully"}


# Add this endpoint to the meal_plans router
@router.get("/{meal_plan_id}/shopping-list", response_model=schemas.ShoppingList)
async def create_shopping_list(
    meal_plan_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
):
    meal_plan = _get_owned_plan(db, meal_plan_id, user)
    return generate_shopping_list(meal_plan, db)
