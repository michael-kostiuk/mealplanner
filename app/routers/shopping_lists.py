from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/shopping-lists", tags=["shopping-lists"])


def generate_shopping_list(meal_plan: models.MealPlan, db: Session):
    ingredients_needed = defaultdict(float)

    for entry in meal_plan.entries:
        recipe = db.query(models.Recipe).get(entry.recipe_id)
        if not recipe:
            continue

        multiplier = entry.servings / recipe.servings
        for recipe_ingredient in recipe.ingredients:
            key = (recipe_ingredient.ingredient_id, recipe_ingredient.unit)
            ingredients_needed[key] += recipe_ingredient.quantity * multiplier

    shopping_list = models.ShoppingList(
        meal_plan_id=meal_plan.id, created_at=datetime.utcnow(), status="active"
    )
    db.add(shopping_list)
    db.commit()

    for (ingredient_id, unit), quantity in ingredients_needed.items():
        ingredient = db.query(models.Ingredient).get(ingredient_id)
        item = models.ShoppingListItem(
            shopping_list_id=shopping_list.id,
            ingredient_id=ingredient_id,
            quantity=quantity,
            unit=unit,
            category=ingredient.category,
        )
        db.add(item)

    db.commit()
    db.refresh(shopping_list)
    return shopping_list


@router.get("/", response_model=list[schemas.ShoppingList])
async def list_shopping_lists(db: Session = Depends(get_db)):
    return db.query(models.ShoppingList).all()


@router.get("/{shopping_list_id}", response_model=schemas.ShoppingList)
async def get_shopping_list(shopping_list_id: int, db: Session = Depends(get_db)):
    shopping_list = (
        db.query(models.ShoppingList).filter(models.ShoppingList.id == shopping_list_id).first()
    )
    if not shopping_list:
        raise HTTPException(status_code=404, detail="Shopping list not found")
    return shopping_list


@router.delete("/{shopping_list_id}")
async def delete_shopping_list(shopping_list_id: int, db: Session = Depends(get_db)):
    shopping_list = (
        db.query(models.ShoppingList).filter(models.ShoppingList.id == shopping_list_id).first()
    )
    if not shopping_list:
        raise HTTPException(status_code=404, detail="Shopping list not found")

    db.delete(shopping_list)
    db.commit()
    return {"message": "Shopping list deleted successfully"}


@router.get("/{shopping_list_id}/export")
async def export_shopping_list(
    shopping_list_id: int, format: str = "ios_reminders", db: Session = Depends(get_db)
):
    shopping_list = (
        db.query(models.ShoppingList).filter(models.ShoppingList.id == shopping_list_id).first()
    )
    if not shopping_list:
        raise HTTPException(status_code=404, detail="Shopping list not found")

    if format == "ios_reminders":
        # Group items by category
        categories = defaultdict(list)
        for item in shopping_list.items:
            categories[item.category].append(f"{item.quantity} {item.unit} {item.ingredient.name}")

        # Format for iOS Reminders
        reminder_text = ""
        for category, items in categories.items():
            reminder_text += f"\n{category}:\n"
            reminder_text += "\n".join(f"☐ {item}" for item in items)
            reminder_text += "\n"

        return {"format": "ios_reminders", "content": reminder_text.strip()}
    else:
        raise HTTPException(status_code=400, detail="Unsupported export format")


@router.get("/item/{shopping_list_item_id}/recipes", response_model=list[schemas.Recipe])
async def get_recipes_by_shopping_item(shopping_list_item_id: int, db: Session = Depends(get_db)):
    """
    Get all recipes in a meal plan that use a specific shopping list item.

    Args:
        shopping_list_item_id: ID of the shopping list item
    """

    # Validate shopping list item exists
    shopping_item = (
        db.query(models.ShoppingListItem)
        .filter(models.ShoppingListItem.id == shopping_list_item_id)
        .first()
    )

    if not shopping_item:
        raise HTTPException(status_code=404, detail="Shopping list item not found")

    # Get all recipes in the meal plan that use this ingredient
    recipes = (
        db.query(models.Recipe)
        .join(models.RecipeIngredient, models.Recipe.id == models.RecipeIngredient.recipe_id)
        .join(models.MealPlanEntry, models.Recipe.id == models.MealPlanEntry.recipe_id)
        .filter(
            models.RecipeIngredient.ingredient_id == shopping_item.ingredient_id,
            models.MealPlanEntry.meal_plan_id == shopping_item.shopping_list.meal_plan_id,
        )
        .distinct()
        .all()
    )

    return recipes
