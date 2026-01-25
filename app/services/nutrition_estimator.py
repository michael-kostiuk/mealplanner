"""
Nutrition Estimator Service using Google AI (Gemini) API

This service estimates nutritional information for recipes based on ingredients.
"""

import logging

from pydantic import BaseModel

from app.core.google_ai_client import (
    GoogleAIParseError,
    GoogleAIRateLimitError,
    GoogleAIRequestError,
    extract_json,
    get_google_ai_client,
)

logger = logging.getLogger(__name__)


class IngredientInput(BaseModel):
    """Input model for a single ingredient with quantity."""

    name: str
    quantity: float
    unit: str


class NutritionData(BaseModel):
    """Nutritional information returned by the AI."""

    calories: float
    protein: float
    carbs: float
    fats: float


class NutritionEstimationError(Exception):
    """Custom exception for nutrition estimation errors."""

    def __init__(self, message: str, is_rate_limited: bool = False):
        self.message = message
        self.is_rate_limited = is_rate_limited
        super().__init__(self.message)


class NutritionEstimator:
    """
    Service for estimating nutritional information using Google's Gemini AI.
    """

    DEFAULT_GEMINI_MODEL = "gemma-3-27b-it"

    def __init__(self, model: str | None = None):
        self._client = get_google_ai_client()
        self._model = model or self.DEFAULT_GEMINI_MODEL

    def _format_ingredients_text(self, ingredients: list[IngredientInput]) -> str:
        """Format ingredients into a readable string for the prompt."""
        return " ".join(f"{ing.name} {ing.quantity} {ing.unit}" for ing in ingredients)

    def _build_prompt(self, ingredients: list[IngredientInput], servings: int = 1) -> str:
        """Build the prompt for the AI model."""
        ingredients_text = self._format_ingredients_text(ingredients)
        return f"""
            You are a nutrition calculator.

            Task:
            Estimate nutrition per serving based on the ingredients provided.

            Rules:
            - Output JSON only
            - No explanations or comments
            - Use numeric values (floats)
            - Units: calories in kcal, macros in grams
            - If information is missing, estimate reasonably

            Output format:
            {{"calories":0,"protein":0,"carbs":0,"fats":0}}

            Ingredients:
            {ingredients_text}
            Servings:
            {servings}
            """.strip()

    def _parse_response(self, response_data: dict) -> NutritionData:
        """Parse the AI response and extract nutrition data."""
        try:
            nutrition_dict = extract_json(response_data)
            return NutritionData(
                calories=float(nutrition_dict.get("calories", 0)),
                protein=float(nutrition_dict.get("protein", 0)),
                carbs=float(nutrition_dict.get("carbs", 0)),
                fats=float(nutrition_dict.get("fats", 0)),
            )
        except GoogleAIParseError as exc:
            raise NutritionEstimationError(str(exc)) from exc

    async def estimate_nutrition(
        self, ingredients: list[IngredientInput], servings: int | None = 1
    ) -> NutritionData:
        """
        Estimate nutritional information for a list of ingredients.

        Args:
            ingredients: List of ingredients with quantities and units

        Returns:
            NutritionData with estimated calories, protein, carbs, and fats

        Raises:
            NutritionEstimationError: If the estimation fails
        """
        if not ingredients:
            raise NutritionEstimationError("No ingredients provided")

        prompt = self._build_prompt(ingredients, servings)

        # Build the request payload for Gemini API
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for more consistent results
                "maxOutputTokens": 256,
            },
        }

        try:
            response_data = await self._client.generate_content(self._model, payload, timeout=30.0)
            return self._parse_response(response_data)
        except GoogleAIRateLimitError as exc:
            raise NutritionEstimationError(
                "Rate limit exceeded. Please try again later.",
                is_rate_limited=True,
            ) from exc
        except (GoogleAIRequestError, GoogleAIParseError) as exc:
            logger.error("Request failed: %s", exc)
            raise NutritionEstimationError(str(exc)) from exc


# Singleton instance
_estimator: NutritionEstimator | None = None


def get_nutrition_estimator() -> NutritionEstimator:
    """Get or create the nutrition estimator instance."""
    global _estimator
    if _estimator is None:
        _estimator = NutritionEstimator()
    return _estimator
