from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, ConfigDict

class IngredientBase(BaseModel):
    name: str
    category: str
    base_unit: str
    calories: float
    protein: float
    carbs: float
    fats: float

class IngredientCreate(IngredientBase):
    pass

class Ingredient(IngredientBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class RecipeIngredientBase(BaseModel):
    ingredient_id: int
    quantity: float
    unit: str

class RecipeIngredientCreate(RecipeIngredientBase):
    pass

class RecipeIngredient(RecipeIngredientBase):
    recipe_id: int
    ingredient: Ingredient
    model_config = ConfigDict(from_attributes=True)

class RecipeBase(BaseModel):
    name: str
    servings: int
    prep_time: int
    cook_time: int
    instructions: str
    category: str
    dietary_tags: List[str]
    calories: int
    protein: float
    carbs: float
    fats: float
    breakfast_weight: float
    lunch_weight: float
    dinner_weight: float

class RecipeCreate(RecipeBase):
    ingredients: List[RecipeIngredientCreate]

class Recipe(RecipeBase):
    id: int
    created_at: datetime
    ingredients: List[RecipeIngredient]
    model_config = ConfigDict(from_attributes=True)

class MealPlanEntryBase(BaseModel):
    recipe_id: int
    date: datetime
    meal_type: str
    servings: int

class MealPlanEntryCreate(MealPlanEntryBase):
    pass

class MealPlanEntry(MealPlanEntryBase):
    id: int
    meal_plan_id: int
    recipe: Recipe
    model_config = ConfigDict(from_attributes=True)

class MealPlanBase(BaseModel):
    start_date: datetime
    end_date: datetime
    people_count: int
    target_calories: int
    dietary_preferences: List[str]

class MealPlanCreate(MealPlanBase):
    entries: List[MealPlanEntryCreate]

class MealPlan(MealPlanBase):
    id: int
    user_id: int
    created_at: datetime
    entries: List[MealPlanEntry]
    model_config = ConfigDict(from_attributes=True)

class ShoppingListItemBase(BaseModel):
    ingredient_id: int
    quantity: float
    unit: str
    category: str
    status: str = 'pending'

class ShoppingListItem(ShoppingListItemBase):
    id: int
    shopping_list_id: int
    ingredient: Ingredient
    model_config = ConfigDict(from_attributes=True)

class ShoppingListBase(BaseModel):
    meal_plan_id: int
    status: str = 'active'
    export_format: Optional[str] = None

class ShoppingListCreate(ShoppingListBase):
    pass

class ShoppingList(ShoppingListBase):
    id: int
    created_at: datetime
    items: List[ShoppingListItem]
    model_config = ConfigDict(from_attributes=True)

class UserBase(BaseModel):
    email: str
    calorie_target: int
    dietary_preferences: Optional[str] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    meal_plans: List[MealPlan]
    model_config = ConfigDict(from_attributes=True)