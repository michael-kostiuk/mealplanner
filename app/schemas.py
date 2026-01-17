from datetime import datetime
from typing import List, Optional, Dict, Literal, Any
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
    calories: int
    protein: float
    carbs: float
    fats: float
    breakfast_weight: float
    lunch_weight: float
    dinner_weight: float
    image_url: Optional[str] = None

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


class ParsedIngredientFromImage(BaseModel):
    raw_name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    preparation: Optional[str] = None
    matched_ingredient_id: Optional[int] = None
    matched_ingredient_name: Optional[str] = None
    match_confidence: float = 0.0
    match_type: Literal["exact", "fuzzy_high", "ai_verified", "unmatched"] = "unmatched"
    needs_review: bool = True


class ParsedRecipeFromImage(BaseModel):
    name: Optional[str] = None
    servings: Optional[int] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    instructions: Optional[str] = None
    category: Optional[str] = None
    ingredients: List[ParsedIngredientFromImage] = []
    nutrition: Optional[Dict[str, float]] = None
    warnings: List[str] = []
    raw: Optional[Dict[str, Any]] = None


class RecipeFromImageStartResponse(BaseModel):
    job_id: str


class RecipeFromImageJob(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "failed", "canceled"] = "queued"
    current_step: str = ""
    step_progress: int = 0
    overall_progress: int = 0
    result: Optional[ParsedRecipeFromImage] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
