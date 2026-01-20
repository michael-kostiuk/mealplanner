"""
Nutrition estimation endpoints.

Provides AI-powered nutritional information estimation for recipes.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import logging

from ..services.nutrition_estimator import (
    NutritionEstimator,
    NutritionData,
    IngredientInput,
    NutritionEstimationError,
    get_nutrition_estimator
)

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/nutrition",
    tags=["nutrition"]
)


class EstimateNutritionRequest(BaseModel):
    """Request body for nutrition estimation endpoint."""
    ingredients: List[IngredientInput]
    servings: int = 1
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ingredients": [
                        {"name": "Борошно цільнозернове", "quantity": 30, "unit": "g"},
                        {"name": "Творог 5%", "quantity": 100, "unit": "g"},
                        {"name": "Жовток", "quantity": 1, "unit": "piece"},
                        {"name": "Мʼякий творог", "quantity": 100, "unit": "g"},
                        {"name": "Абрикос", "quantity": 50, "unit": "g"}
                    ]
                }
            ]
        }
    }


class EstimateNutritionResponse(BaseModel):
    """Response body for nutrition estimation endpoint."""
    calories: float
    protein: float
    carbs: float
    fats: float
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "calories": 450.5,
                    "protein": 35.2,
                    "carbs": 28.0,
                    "fats": 18.5
                }
            ]
        }
    }


class ErrorResponse(BaseModel):
    """Error response model."""
    detail: str
    is_rate_limited: bool = False


@router.post(
    "/estimate",
    response_model=EstimateNutritionResponse,
    responses={
        200: {"description": "Successful nutrition estimation"},
        400: {"description": "Invalid request (e.g., empty ingredients list)"},
        429: {"description": "Rate limited by the AI service"},
        500: {"description": "Internal server error or AI service unavailable"},
        503: {"description": "AI service configuration error"}
    }
)
async def estimate_nutrition(request: EstimateNutritionRequest):
    """
    Estimate nutritional information for a recipe based on its ingredients.
    
    This endpoint uses Google's Gemini AI to analyze the provided ingredients
    and estimate the total nutritional values including calories, protein,
    carbohydrates, and fats.
    
    **Request body:**
    - `ingredients`: List of ingredients with name, quantity, and unit
    
    **Response:**
    - `calories`: Estimated total calories
    - `protein`: Estimated protein in grams
    - `carbs`: Estimated carbohydrates in grams  
    - `fats`: Estimated fats in grams
    
    **Error responses:**
    - 400: Empty ingredients list
    - 429: Rate limited (try again later)
    - 500: AI service error
    - 503: API key not configured
    """
    estimator = get_nutrition_estimator()

    try:
        nutrition_data = await estimator.estimate_nutrition(request.ingredients, request.servings)
        return EstimateNutritionResponse(
            calories=nutrition_data.calories,
            protein=nutrition_data.protein,
            carbs=nutrition_data.carbs,
            fats=nutrition_data.fats
        )
    except NutritionEstimationError as e:
        if e.is_rate_limited:
            raise HTTPException(status_code=429, detail=e.message)
        elif "API key not configured" in e.message or "environment variable is not set" in e.message:
            raise HTTPException(status_code=503, detail=e.message)
        else:
            raise HTTPException(status_code=500, detail=e.message)
