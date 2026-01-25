from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class IngredientImportDraft(BaseModel):
    raw_name: str
    quantity: float | None = None
    unit: str | None = None
    preparation: str | None = None
    matched_ingredient_id: int | None = None
    matched_ingredient_name: str | None = None
    match_confidence: float = 0.0
    match_type: Literal["exact", "fuzzy_high", "ai_verified", "unmatched"] = "unmatched"
    needs_review: bool = True


class RecipeImportDraft(BaseModel):
    name: str | None = None
    servings: int | None = None
    prep_time: int | None = None
    cook_time: int | None = None
    instructions: str | None = None
    category: str | None = None
    ingredients: list[IngredientImportDraft] = []
    nutrition: dict[str, float] | None = None
    warnings: list[str] = []


class RecipeImportJob(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "failed", "canceled"] = "queued"
    current_step: str = ""
    step_progress: int = 0
    overall_progress: int = 0
    result: RecipeImportDraft | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class RecipeImportStartResponse(BaseModel):
    job_id: str
