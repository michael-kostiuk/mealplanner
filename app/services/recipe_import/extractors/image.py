import base64
import logging
from typing import Any

from app.core.google_ai_client import (
    GoogleAIParseError,
    GoogleAIRateLimitError,
    GoogleAIRequestError,
    extract_json,
    get_google_ai_client,
)

from ..schemas import IngredientImportDraft, RecipeImportDraft
from ..utils import safe_parse_float, safe_parse_int
from .base import BaseExtractor

logger = logging.getLogger(__name__)

RECIPE_EXTRACTION_PROMPT_UA = (
    "Ти витягуєш рецепт з фото. Поверни лише валідний JSON без пояснень.\n"
    "Мова відповіді: українська.\n\n"
    "ВАЖЛИВІ ПРАВИЛА:\n"
    "1. servings (порції): якщо не вказано явно, оціни на основі кількості інгредієнтів та розміру страви\n"
    "2. ingredients (інгредієнти):\n"
    "   - НЕ дублюй однакові інгредієнти навіть з різною метою (наприклад, цукор для тіста і цукор для посипання - це один інгредієнт з загальною кількістю)\n"
    '   - name: використовуй коротку нормалізовану назву інгредієнта (наприклад, "яловичина", "сир", не "шматок яловичини")\n'
    "   - quantity: число (можна дробове), не мішай з одиницями виміру\n"
    "   - unit: тільки одиниця виміру (g, kg, ml, l, cup, tbsp, tsp, piece, slice, clove, bunch, can, package), не пиши число в цьому полі\n"
    "   - НЕ використовуй поле preparation для інгредієнтів\n"
    "3. Одиниці виміру: використовуй лише ці значення: g, kg, ml, l, cup, tbsp, tsp, piece, slice, clove, bunch, can, package\n"
    "4. Якщо кількість не вказана явно, quantity=null\n"
    "5. Усі назви інгредієнтів та текст повинні бути звичайним текстом без спеціальних символів або форматування\n\n"
    "Формат:\n"
    "{\n"
    '  "name": string,\n'
    '  "servings": number|null,\n'
    '  "prep_time": number|null,\n'
    '  "cook_time": number|null,\n'
    '  "category": string|null,\n'
    '  "ingredients": [\n'
    "    {\n"
    '      "name": string,\n'
    '      "quantity": number|string|null,\n'
    '      "unit": string|null\n'
    "    }\n"
    "  ],\n"
    '  "instructions": string|null\n'
    "}\n"
)


class ImageExtractor(BaseExtractor):
    DEFAULT_GEMINI_MODEL = "gemma-3-27b-it"

    def __init__(self, model: str | None = None):
        self._client = get_google_ai_client()
        self._model = model or self.DEFAULT_GEMINI_MODEL

    async def extract(self, input_data: bytes, **kwargs) -> RecipeImportDraft:
        """
        Extract recipe from image bytes.
        kwargs should contain 'mime_type'.
        """
        mime_type = kwargs.get("mime_type")
        if not mime_type:
            raise ValueError("mime_type is required for ImageExtractor")

        logger.info("Calling Gemini API for recipe extraction")
        image_b64 = base64.b64encode(input_data).decode("ascii")
        prompt = RECIPE_EXTRACTION_PROMPT_UA
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
        }
        try:
            data = await self._client.generate_content(self._model, payload, timeout=60.0)
        except GoogleAIRateLimitError as exc:
            raise RuntimeError("Rate limit exceeded by AI service (429)") from exc
        except GoogleAIRequestError as exc:
            raise RuntimeError(f"AI request failed: {exc}") from exc

        try:
            extracted = extract_json(data)
        except GoogleAIParseError as exc:
            raise RuntimeError(str(exc)) from exc

        return self._to_draft(extracted)

    def _to_draft(self, extracted: dict[str, Any]) -> RecipeImportDraft:
        ingredients_out: list[IngredientImportDraft] = []
        for ing in extracted.get("ingredients", []) or []:
            name = (ing.get("name") or "").strip()
            if not name:
                continue
            ingredients_out.append(
                IngredientImportDraft(
                    raw_name=name,
                    quantity=safe_parse_float(ing.get("quantity")),
                    unit=(ing.get("unit") or None),
                    preparation=None,
                    matched_ingredient_id=None,
                    matched_ingredient_name=None,
                    match_confidence=0.0,
                    match_type="unmatched",
                    needs_review=True,
                )
            )
        return RecipeImportDraft(
            name=(extracted.get("name") or None),
            servings=safe_parse_int(extracted.get("servings")),
            prep_time=safe_parse_int(extracted.get("prep_time")),
            cook_time=safe_parse_int(extracted.get("cook_time")),
            instructions=(extracted.get("instructions") or None),
            category=(extracted.get("category") or None),
            ingredients=ingredients_out,
            nutrition=None,
            warnings=[],
        )
