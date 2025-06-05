from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from ..database import get_db
from .. import models, schemas
import random
from .shopping_lists import generate_shopping_list

router = APIRouter(
    prefix="/meal-plans",
    tags=["meal-plans"]
)

def calculate_daily_meals(recipes: List[models.Recipe], target_calories: int, dietary_preferences: List[str]):
    # Filter recipes by dietary preferences
    suitable_recipes = [r for r in recipes if all(pref in r.dietary_tags for pref in dietary_preferences)]
    
    # Sort recipes by meal type weights
    breakfast_recipes = sorted(suitable_recipes, key=lambda x: x.breakfast_weight, reverse=True)
    lunch_recipes = sorted(suitable_recipes, key=lambda x: x.lunch_weight, reverse=True)
    dinner_recipes = sorted(suitable_recipes, key=lambda x: x.dinner_weight, reverse=True)
    
    # Calculate target calories per meal
    breakfast_calories = target_calories * 0.25  # 25% for breakfast
    lunch_calories = target_calories * 0.35    # 35% for lunch
    dinner_calories = target_calories * 0.40    # 40% for dinner
    
    # Select recipes that best match calorie targets
    selected_meals = {
        'breakfast': next((r for r in breakfast_recipes if 0.8 <= r.calories/breakfast_calories <= 1.2), breakfast_recipes[0]),
        'lunch': next((r for r in lunch_recipes if 0.8 <= r.calories/lunch_calories <= 1.2), lunch_recipes[0]),
        'dinner': next((r for r in dinner_recipes if 0.8 <= r.calories/dinner_calories <= 1.2), dinner_recipes[0])
    }
    
    return selected_meals

@router.get("/", response_model=List[schemas.MealPlan])
async def list_meal_plans(user_id: int, db: Session = Depends(get_db)):
    return db.query(models.MealPlan).filter(models.MealPlan.user_id == user_id).all()

@router.post("/", response_model=schemas.MealPlan)
async def create_meal_plan(meal_plan: schemas.MealPlanCreate, db: Session = Depends(get_db)):
    db_meal_plan = models.MealPlan(
        user_id=meal_plan.user_id,
        start_date=meal_plan.start_date,
        end_date=meal_plan.end_date,
        people_count=meal_plan.people_count,
        target_calories=meal_plan.target_calories,
        dietary_preferences=meal_plan.dietary_preferences
    )
    db.add(db_meal_plan)
    db.commit()
    db.refresh(db_meal_plan)
    
    # Create meal plan entries
    for entry in meal_plan.entries:
        db_entry = models.MealPlanEntry(
            meal_plan_id=db_meal_plan.id,
            **entry.model_dump()
        )
        db.add(db_entry)
    
    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan

@router.post("/auto-generate", response_model=schemas.MealPlan)
async def auto_generate_meal_plan(
    start_date: datetime,
    days: int,
    target_calories: int,
    people_count: int,
    dietary_preferences: List[str] = Query([]),
    user_id: int = Query(...),
    db: Session = Depends(get_db)
):
    # Get all available recipes
    recipes = db.query(models.Recipe).all()
    if not recipes:
        raise HTTPException(status_code=400, detail="No recipes available for meal planning")
    
    # Create meal plan
    db_meal_plan = models.MealPlan(
        user_id=user_id,
        start_date=start_date,
        end_date=start_date + timedelta(days=days),
        people_count=people_count,
        target_calories=target_calories,
        dietary_preferences=dietary_preferences
    )
    db.add(db_meal_plan)
    db.commit()
    db.refresh(db_meal_plan)
    
    # Generate meals for each day
    current_date = start_date
    for _ in range(days):
        daily_meals = calculate_daily_meals(recipes, target_calories, dietary_preferences)
        
        for meal_type, recipe in daily_meals.items():
            db_entry = models.MealPlanEntry(
                meal_plan_id=db_meal_plan.id,
                recipe_id=recipe.id,
                date=current_date,
                meal_type=meal_type,
                servings=people_count
            )
            db.add(db_entry)
        
        current_date += timedelta(days=1)
    
    db.commit()
    db.refresh(db_meal_plan)
    return db_meal_plan

@router.get("/{meal_plan_id}", response_model=schemas.MealPlan)
async def get_meal_plan(meal_plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if meal_plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    return meal_plan

@router.put("/{meal_plan_id}", response_model=schemas.MealPlan)
async def update_meal_plan(meal_plan_id: int, meal_plan: schemas.MealPlanCreate, db: Session = Depends(get_db)):
    db_meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if db_meal_plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    
    # Update meal plan attributes
    for key, value in meal_plan.model_dump(exclude={'entries'}).items():
        setattr(db_meal_plan, key, value)
    
    # Update entries
    db.query(models.MealPlanEntry).filter(models.MealPlanEntry.meal_plan_id == meal_plan_id).delete()
    
    for entry in meal_plan.entries:
        db_entry = models.MealPlanEntry(
            meal_plan_id=meal_plan_id,
            **entry.model_dump()
        )
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
async def update_meal(meal_plan_id: int, meal_id: int, meal: schemas.MealPlanEntryCreate, db: Session = Depends(get_db)):
    db_meal = db.query(models.MealPlanEntry).filter(
        models.MealPlanEntry.id == meal_id,
        models.MealPlanEntry.meal_plan_id == meal_plan_id
    ).first()
    
    if db_meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")
    
    for key, value in meal.model_dump().items():
        setattr(db_meal, key, value)
    
    db.commit()
    db.refresh(db_meal)
    return db_meal

# Add this endpoint to the meal_plans router
@router.get("/{meal_plan_id}/shopping-list", response_model=schemas.ShoppingList)
async def create_shopping_list(meal_plan_id: int, db: Session = Depends(get_db)):
    meal_plan = db.query(models.MealPlan).filter(models.MealPlan.id == meal_plan_id).first()
    if not meal_plan:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    
    return generate_shopping_list(meal_plan, db)