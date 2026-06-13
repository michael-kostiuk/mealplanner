from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.units import BaseUnit, normalize_unit


def _validate_base_unit(value):
    """Shared base_unit normalization logic."""
    normalized = normalize_unit(value)
    if not normalized:
        raise ValueError("Unsupported base unit")
    return normalized


class IngredientBase(BaseModel):
    name: str
    category: str
    base_unit: BaseUnit
    calories: float
    protein: float
    carbs: float
    fats: float

    @field_validator("base_unit", mode="before")
    @classmethod
    def _normalize_base_unit(cls, value):
        return _validate_base_unit(value)

    @field_serializer("calories", "protein", "carbs", "fats")
    def _serialize_macros(self, value: float):
        return round(value, 2)


class IngredientCreate(BaseModel):
    """Schema for creating ingredients. Nutrition fields are optional - if not provided,
    they will be estimated asynchronously using FDC lookup or AI."""

    name: str
    category: str
    base_unit: BaseUnit
    calories: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fats: float | None = None

    @field_validator("base_unit", mode="before")
    @classmethod
    def _normalize_base_unit(cls, value):
        return _validate_base_unit(value)


class Ingredient(IngredientBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class IngredientNutritionEstimateFailure(BaseModel):
    id: int
    reason: str
    rate_limited: bool = False


class IngredientBulkEstimateResponse(BaseModel):
    updated: list[Ingredient]
    updated_count: int
    skipped_count: int
    failed: list[IngredientNutritionEstimateFailure]


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
    image_url: str | None = None


class RecipeCreate(RecipeBase):
    ingredients: list[RecipeIngredientCreate]


class Recipe(RecipeBase):
    id: int
    created_at: datetime
    ingredients: list[RecipeIngredient]
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
    dietary_preferences: list[str]


class MealPlanCreate(MealPlanBase):
    entries: list[MealPlanEntryCreate]


class MealPlan(MealPlanBase):
    id: int
    user_id: int
    created_at: datetime
    entries: list[MealPlanEntry]
    model_config = ConfigDict(from_attributes=True)


class ShoppingListItemBase(BaseModel):
    ingredient_id: int
    quantity: float
    unit: str
    category: str
    status: str = "pending"


class ShoppingListItem(ShoppingListItemBase):
    id: int
    shopping_list_id: int
    ingredient: Ingredient
    model_config = ConfigDict(from_attributes=True)


class ShoppingListBase(BaseModel):
    meal_plan_id: int
    status: str = "active"
    export_format: str | None = None


class ShoppingListCreate(ShoppingListBase):
    pass


class ShoppingList(ShoppingListBase):
    id: int
    created_at: datetime
    items: list[ShoppingListItem]
    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    email: str
    calorie_target: int
    dietary_preferences: str | None = None


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    meal_plans: list[MealPlan]
    model_config = ConfigDict(from_attributes=True)


class FavoriteBase(BaseModel):
    recipe_id: int


class FavoriteCreate(FavoriteBase):
    pass


class Favorite(FavoriteBase):
    id: int
    user_id: int
    created_at: datetime
    recipe: Recipe
    model_config = ConfigDict(from_attributes=True)


class ShoppingListItemUpdate(BaseModel):
    status: str | None = None


from app.services.recipe_import.schemas import (
    IngredientImportDraft,
    RecipeImportDraft,
    RecipeImportJob,
    RecipeImportStartResponse,
)

# Aliases for backward compatibility and to avoid duplication
ParsedIngredientFromImage = IngredientImportDraft
ParsedRecipeFromImage = RecipeImportDraft
RecipeFromImageStartResponse = RecipeImportStartResponse
RecipeFromImageJob = RecipeImportJob
