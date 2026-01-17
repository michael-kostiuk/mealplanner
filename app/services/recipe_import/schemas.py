from datetime import datetime
from typing import List, Optional, Dict, Literal
from pydantic import BaseModel

class IngredientImportDraft(BaseModel):
    raw_name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    preparation: Optional[str] = None
    matched_ingredient_id: Optional[int] = None
    matched_ingredient_name: Optional[str] = None
    match_confidence: float = 0.0
    match_type: Literal["exact", "fuzzy_high", "ai_verified", "unmatched"] = "unmatched"
    needs_review: bool = True

class RecipeImportDraft(BaseModel):
    name: Optional[str] = None
    servings: Optional[int] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    instructions: Optional[str] = None
    category: Optional[str] = None
    ingredients: List[IngredientImportDraft] = []
    nutrition: Optional[Dict[str, float]] = None
    warnings: List[str] = []

class RecipeImportJob(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "failed", "canceled"] = "queued"
    current_step: str = ""
    step_progress: int = 0
    overall_progress: int = 0
    result: Optional[RecipeImportDraft] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class RecipeImportStartResponse(BaseModel):
    job_id: str
