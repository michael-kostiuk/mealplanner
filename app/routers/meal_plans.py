import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import MealPlanGenerator
from .shopping_lists import generate_shopping_list

logger = logging.getLogger(__name__)


def get_user(db: Session = Depends(get_db)):
    usr = db.query(models.User).filter(models.User.id == 1).first()
    if not usr:
        usr = models.User(id=1, email="test@example.com")
        db.add(usr)
        db.commit()
        db.refresh(usr)
    return usr


router = APIRouter(
    prefix="/meal-plans",
    tags=["meal-plans"],
    dependencies=[Depends(get_user)],
)


@router.get("/", response_model=list[schemas.MealPlan])
async def list_meal_plans(user_id: int, db: Session = Depends(get_db)):
    return db.query(models.MealPlan).filter(models.MealPlan.user_id == user_id).all()


@router.post("/", response_model=schemas.MealPlan)
async def create_meal_plan(meal_plan: schemas.MealPlanCreate, db: Session = Depends(get_db)):
    db_meal_plan = models.MealPlan(
        user_id=1,
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
        db_entry = models.MealPlanEntry(meal_plan_id=db_meal_plan.id, **entry.model_dump())
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
    user_id: int | None = Query(None),
    meal_plan_id: int | None = Query(None, alias="id"),
    db: Session = Depends(get_db),
):
    # Get all available recipes
    if db.query(models.Recipe.id).first() is None:
        raise HTTPException(status_code=400, detail="No recipes available for meal planning")

    planner = MealPlanGenerator(db)
    if meal_plan_id is not None:
        meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
        if meal_plan is None:
            raise HTTPException(status_code=404, detail="Meal plan not found")
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
            "user_id": user_id,
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
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan


@router.post("/suggest-meal", response_model=schemas.Recipe)
async def suggest_meal(req: schemas.MealSuggestRequest, db: Session = Depends(get_db)):
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return recipe


@router.get("/{meal_plan_id}", response_model=schemas.MealPlan)
async def get_meal_plan(meal_plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if meal_plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    return meal_plan


@router.put("/{meal_plan_id}", response_model=schemas.MealPlan)
async def update_meal_plan(
    meal_plan_id: int, meal_plan: schemas.MealPlanCreate, db: Session = Depends(get_db)
):
    db_meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if db_meal_plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")

    # Update meal plan attributes
    for key, value in meal_plan.model_dump(exclude={"entries"}).items():
        setattr(db_meal_plan, key, value)

    # Update entries
    db.query(models.MealPlanEntry).filter(
        models.MealPlanEntry.meal_plan_id == meal_plan_id
    ).delete()

    for entry in meal_plan.entries:
        db_entry = models.MealPlanEntry(meal_plan_id=meal_plan_id, **entry.model_dump())
        db.add(db_entry)

    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan


@router.delete("/{meal_plan_id}")
async def delete_meal_plan(meal_plan_id: int, db: Session = Depends(get_db)):
    db_meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if db_meal_plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")

    db.delete(db_meal_plan)
    db.commit()
    return {"message": "Meal plan deleted successfully"}


@router.put("/{meal_plan_id}/meals/{meal_id}", response_model=schemas.MealPlanEntry)
async def update_meal(
    meal_plan_id: int,
    meal_id: int,
    meal: schemas.MealPlanEntryCreate,
    db: Session = Depends(get_db),
):
    db_meal = (
        db.query(models.MealPlanEntry)
        .filter(
            models.MealPlanEntry.id == meal_id, models.MealPlanEntry.meal_plan_id == meal_plan_id
        )
        .first()
    )

    if db_meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    for key, value in meal.model_dump().items():
        setattr(db_meal, key, value)

    db.commit()
    db.refresh(db_meal)
    return db_meal


@router.post("/{meal_plan_id}/meals", response_model=schemas.MealPlanEntry)
async def add_meal(
    meal_plan_id: int,
    meal: schemas.MealPlanEntryCreate,
    db: Session = Depends(get_db),
):
    """Add a new meal to a meal plan."""
    meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if meal_plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")

    # Verify recipe exists
    recipe = db.query(models.Recipe).filter(models.Recipe.id == meal.recipe_id).first()
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    db_meal = models.MealPlanEntry(meal_plan_id=meal_plan_id, **meal.model_dump())
    db.add(db_meal)
    db.commit()
    db.refresh(db_meal)
    return db_meal


@router.delete("/{meal_plan_id}/meals/{meal_id}")
async def delete_meal(
    meal_plan_id: int,
    meal_id: int,
    db: Session = Depends(get_db),
):
    """Remove a meal from a meal plan."""
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
async def create_shopping_list(meal_plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if not meal_plan:
        raise HTTPException(status_code=404, detail="Meal plan not found")

    return generate_shopping_list(meal_plan, db)
