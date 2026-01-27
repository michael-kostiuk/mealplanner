"""
Ingredient translation service using Google AI (Gemini) API.

Translates ingredient names to English for improved FDC lookup.
"""

import json
import logging

from app.core.google_ai_client import (
    GoogleAIParseError,
    GoogleAIRateLimitError,
    GoogleAIRequestError,
    extract_json,
    get_google_ai_client,
)

logger = logging.getLogger(__name__)


class IngredientTranslationError(Exception):
    """Custom exception for ingredient translation errors."""

    def __init__(self, message: str, is_rate_limited: bool = False):
        self.message = message
        self.is_rate_limited = is_rate_limited
        super().__init__(self.message)


class IngredientTranslator:
    """
    Translate ingredient names to English, optimized for USDA FDC lookup.
    """

    DEFAULT_GEMINI_MODEL = "gemma-3-27b-it"

    def __init__(self, model: str | None = None):
        self._client = get_google_ai_client()
        self._model = model or self.DEFAULT_GEMINI_MODEL
        self._cache: dict[str, str | None] = {}

    def _build_prompt(self, ingredient_name: str) -> str:
        ingredient_json = json.dumps(ingredient_name, ensure_ascii=False)
        return (
            "Translate ingredient names to English for USDA FoodData Central lookup.\n"
            'Return JSON only: {"translation":"..."}\n'
            "Rules:\n"
            "- Output a short, plain English ingredient name optimized for USDA FDC search.\n"
            "- Remove quantities, units, brands.\n"
            "- Keep preservation/processing methods: canned, frozen, dried, smoked, pickled.\n"
            "- Be specific enough to match a single raw ingredient: disambiguate part vs whole, "
            "include color/type when the generic term has common variants, "
            "choose ingredient over dish name.\n"
            "- If unclear or not a food ingredient, return an empty string.\n"
            "\n"
            "Examples:\n"
            "- 'kuryache file' -> 'chicken breast' (Ukrainian transliteration)\n"
            "- 'yaytse' -> 'whole egg' (not 'egg' which could match yolk)\n"
            "- 'rys' -> 'white rice' (default color when unspecified)\n"
            "- 'salat' -> 'lettuce' (ingredient, not dish)\n"
            "- 'oliya' -> 'vegetable oil' (generic oil = vegetable)\n"
            "- 'kukurudza konservovana' -> 'canned corn' (keep processing method)\n"
            "\n"
            f"Ingredient: {ingredient_json}"
        )

    def _parse_response(self, response_data: dict) -> str:
        try:
            parsed = extract_json(response_data)
        except GoogleAIParseError as exc:
            raise IngredientTranslationError(str(exc)) from exc
        translation = (parsed.get("translation") or "").strip()
        return translation

    async def translate_to_english(self, ingredient_name: str) -> str | None:
        if not ingredient_name:
            return None
        ingredient_name = ingredient_name.strip()
        if not ingredient_name:
            return None
        if ingredient_name in self._cache:
            cached = self._cache[ingredient_name]
            return cached or None

        prompt = self._build_prompt(ingredient_name)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 64,
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"translation": {"type": "string"}},
                    "required": ["translation"],
                },
            },
        }

        try:
            response_data = await self._client.generate_content(self._model, payload, timeout=30.0)
            translation = self._parse_response(response_data)
        except GoogleAIRateLimitError as exc:
            raise IngredientTranslationError(
                "Rate limit exceeded. Please try again later.",
                is_rate_limited=True,
            ) from exc
        except (GoogleAIRequestError, GoogleAIParseError) as exc:
            logger.error("Translation request failed: %s", exc)
            raise IngredientTranslationError(str(exc)) from exc

        self._cache[ingredient_name] = translation
        return translation or None


_translator: IngredientTranslator | None = None


def get_ingredient_translator() -> IngredientTranslator:
    """Get or create the ingredient translator instance."""
    global _translator
    if _translator is None:
        _translator = IngredientTranslator()
    return _translator
