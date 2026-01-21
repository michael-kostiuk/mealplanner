import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app import models
from app.core.google_ai_client import (
    GoogleAIParseError,
    GoogleAIRateLimitError,
    GoogleAIRequestError,
    extract_json,
    get_google_ai_client,
)
from app.services.nutrition_estimator import IngredientInput, NutritionEstimationError, get_nutrition_estimator
from .schemas import RecipeImportDraft, IngredientImportDraft
from .utils import normalize_text

logger = logging.getLogger(__name__)

class IngredientMatcher:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._candidates: List[Tuple[int, str, str]] = []
        for ing in self._db.query(models.Ingredient).all():
            name = ing.name or ""
            self._candidates.append((ing.id, name, normalize_text(name)))

    def find_best_candidate(self, query: str) -> Optional[Tuple[int, str, float]]:
        qn = normalize_text(query)
        if not qn:
            return None
        for ing_id, name, norm in self._candidates:
            if norm == qn:
                return ing_id, name, 100.0
        choices = {ing_id: norm for ing_id, _, norm in self._candidates}
        match = process.extractOne(qn, choices, scorer=fuzz.WRatio)
        if not match:
            return None
        matched_id, score, _ = match
        original_name = next((n for iid, n, _ in self._candidates if iid == matched_id), None)
        if original_name is None:
            return None
        return matched_id, original_name, float(score)

class RecipeImportPipeline:
    DEFAULT_GEMINI_MODEL = "gemma-3-27b-it"

    def __init__(self, db: Session, model: Optional[str] = None):
        self.db = db
        self._model = model or self.DEFAULT_GEMINI_MODEL

    async def run(self, draft: RecipeImportDraft, progress_callback=None) -> RecipeImportDraft:
        # Merge duplicates
        if progress_callback: await progress_callback("merging", 0)
        draft = self._merge_duplicates(draft)
        
        # Match ingredients
        if progress_callback: await progress_callback("matching", 0)
        draft, verify_pairs = await self._match_ingredients(draft, progress_callback)
        
        # Verify pairs
        if verify_pairs:
            if progress_callback: await progress_callback("verifying", 0)
            verified = await self._verify_pairs(verify_pairs)
            self._apply_verification(draft, verified)
        
        # Estimate nutrition
        if progress_callback: await progress_callback("nutrition", 0)
        draft.nutrition = await self._estimate_nutrition(draft)
        
        return draft

    def _merge_duplicates(self, draft: RecipeImportDraft) -> RecipeImportDraft:
        if not draft.ingredients:
            return draft

        merged: Dict[str, IngredientImportDraft] = {}
        for ing in draft.ingredients:
            raw_name = ing.raw_name.strip()
            if not raw_name:
                continue

            name = normalize_text(raw_name)
            name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
            name = name.strip()
            if not name:
                continue

            if name not in merged:
                merged[name] = ing
            else:
                existing = merged[name]
                qty1 = existing.quantity
                qty2 = ing.quantity
                if qty1 is not None and qty2 is not None:
                    existing.quantity = qty1 + qty2
                elif qty2 is not None:
                    existing.quantity = qty2
                # Keep existing unit if present
                if not existing.unit and ing.unit:
                    existing.unit = ing.unit
                elif existing.unit and ing.unit and existing.unit != ing.unit:
                    draft.warnings.append(f"Merged ingredients '{name}' have different units: {existing.unit} vs {ing.unit}")

        draft.ingredients = list(merged.values())
        return draft

    async def _match_ingredients(self, draft: RecipeImportDraft, progress_callback) -> Tuple[RecipeImportDraft, List[Tuple[int, str, int, str]]]:
        matcher = IngredientMatcher(self.db)
        ingredients: List[IngredientImportDraft] = []
        total = max(1, len(draft.ingredients))
        verify_pairs: List[Tuple[int, str, int, str]] = []

        for idx, ing in enumerate(draft.ingredients):
            best = matcher.find_best_candidate(ing.raw_name)
            if not best:
                ingredients.append(ing)
            else:
                matched_id, matched_name, score = best
                new_ing = ing.model_copy()
                new_ing.matched_ingredient_id = matched_id
                new_ing.matched_ingredient_name = matched_name
                
                if score >= 100.0:
                    new_ing.match_confidence = 1.0
                    new_ing.match_type = "exact"
                    new_ing.needs_review = False
                    ingredients.append(new_ing)
                elif score >= 95.0:
                    new_ing.match_confidence = score / 100.0
                    new_ing.match_type = "fuzzy_high"
                    new_ing.needs_review = False
                    ingredients.append(new_ing)
                elif score >= 85.0:
                    new_ing.match_confidence = score / 100.0
                    new_ing.match_type = "unmatched"
                    new_ing.needs_review = True
                    ingredients.append(new_ing)
                    verify_pairs.append((idx, ing.raw_name, matched_id, matched_name))
                else:
                    ingredients.append(ing)

            if progress_callback:
                step = int(((idx + 1) / total) * 100)
                await progress_callback("matching", step)

        draft.ingredients = ingredients
        return draft, verify_pairs

    async def _verify_pairs(self, pairs: List[Tuple[int, str, int, str]]) -> Dict[int, bool]:
        try:
            client = get_google_ai_client()
        except ValueError:
            return {}

        items = [
            {"index": idx, "a": raw_name, "b": matched_name}
            for idx, raw_name, _, matched_name in pairs
        ]
        prompt = (
            "Порівняй інгредієнти. Поверни лише JSON.\n"
            "Для кожного елемента скажи чи це один і той самий інгредієнт.\n"
            'Формат: {"results":[{"index":0,"same":true}]}\n'
            f"Дані: {json.dumps(items, ensure_ascii=False)}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024},
        }
        try:
            data = await client.generate_content(self._model, payload, timeout=45.0)
            parsed = extract_json(data)
            results = {}
            for item in parsed.get("results", []) or []:
                idx = item.get("index")
                same = item.get("same")
                if isinstance(idx, int) and isinstance(same, bool):
                    results[idx] = same
            return results
        except (GoogleAIRateLimitError, GoogleAIRequestError, GoogleAIParseError) as exc:
            logger.error("Error verifying pairs: %s", exc)
            return {}
        except Exception as exc:
            logger.error("Error verifying pairs: %s", exc)
            return {}

    def _apply_verification(self, draft: RecipeImportDraft, verified: Dict[int, bool]):
        for idx, is_same in verified.items():
            if not is_same:
                continue
            
            if idx < len(draft.ingredients):
                ing = draft.ingredients[idx]
                if ing.matched_ingredient_id and ing.matched_ingredient_name:
                    ing.match_type = "ai_verified"
                    ing.needs_review = False

    async def _estimate_nutrition(self, draft: RecipeImportDraft) -> Optional[Dict[str, float]]:
        estimator = get_nutrition_estimator()
        ingredients: List[IngredientInput] = []
        for ing in draft.ingredients:
            name = ing.matched_ingredient_name or ing.raw_name
            qty = ing.quantity if ing.quantity is not None else 0.0
            unit = ing.unit or "piece"
            ingredients.append(IngredientInput(name=name, quantity=float(qty), unit=unit))
        try:
            servings = draft.servings or 1
            nutrition = await estimator.estimate_nutrition(ingredients, servings)
            return {
                "calories": round(float(nutrition.calories), 2),
                "protein": round(float(nutrition.protein), 2),
                "carbs": round(float(nutrition.carbs), 2),
                "fats": round(float(nutrition.fats), 2),
            }
        except NutritionEstimationError:
            return None
