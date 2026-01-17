#!/usr/bin/env python3
# Recipe from Image Converter
# Usage: docker exec mp-be-1 python scripts/im_to_recipe.py /path/to/image.jpg
# Requirements: GOOGLE_AI_API_KEY environment variable must be set
import asyncio
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import httpx
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import models, schemas
from app.database import SessionLocal
from app.services.nutrition_estimator import IngredientInput, NutritionEstimationError, get_nutrition_estimator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = value.replace("'", "'").replace("", "'").replace("`", "'")
    value = value.replace("", "").replace("'", "")
    value = value.replace(".", "")
    value = value.replace(",", "")
    value = " ".join(value.split())
    return value


def _safe_parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip().replace(",", ".")
    if not s:
        return None
    if "/" in s and all(part.strip().replace(".", "", 1).isdigit() for part in s.split("/", 1)):
        num, den = s.split("/", 1)
        try:
            den_v = float(den)
            if den_v == 0:
                return None
            return float(num) / den_v
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return int(float(s.replace(",", ".")))
    except ValueError:
        return None


def _copy_parsed_ingredient(
    ing: schemas.ParsedIngredientFromImage, **updates: Any
) -> schemas.ParsedIngredientFromImage:
    data = ing.model_dump()
    data.update(updates)
    return schemas.ParsedIngredientFromImage(**data)


class _IngredientMatcher:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._candidates: List[Tuple[int, str, str]] = []
        for ing in self._db.query(models.Ingredient).all():
            name = ing.name or ""
            self._candidates.append((ing.id, name, _normalize_text(name)))

    def find_best_candidate(self, query: str) -> Optional[Tuple[int, str, float]]:
        qn = _normalize_text(query)
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


class RecipeFromImageHelper:
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemma-3-27b-it:generateContent"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def print_step(self, step: str, progress: int = 0) -> None:
        bar_length = 30
        filled = int(bar_length * progress / 100)
        bar = "=" * filled + " " * (bar_length - filled)
        print(f"[{bar}] {step}")

    async def extract_recipe(self, image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        print("\n[extracting] Calling AI to extract recipe from image...")
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = (
            "Ти витягуєш рецепт з фото. Поверни лише валідний JSON без пояснень.\n"
            "Мова відповіді: українська.\n\n"
            "ВАЖЛИВІ ПРАВИЛА:\n"
            "1. servings (порції): якщо не вказано явно, оціни на основі кількості інгредієнтів та розміру страви\n"
            "2. ingredients (інгредієнти):\n"
            "   - НЕ дублюй однакові інгредієнти навіть з різною метою (наприклад, цукор для тіста і цукор для посипання - це один інгредієнт з загальною кількістю)\n"
            "   - name: використовуй коротку нормалізовану назву інгредієнта (наприклад, \"яловичина\", \"сир\", не \"шматок яловичини\")\n"
            "   - quantity: число (можна дробове), не мішай з одиницями виміру\n"
            "   - unit: тільки одиниця виміру (г, кг, мл, л, ч.л, ст.л, шт, склянка), не пиши число в цьому полі\n"
            "   - НЕ використовуй поле preparation для інгредієнтів\n"
            "3. Одиниці виміру: ч.л (чайна ложка), ст.л (столова ложка), г (грами), кг, мл, л, шт\n"
            "4. Якщо кількість не вказана явно, quantity=null\n"
            "5. Усі назви інгредієнтів та текст повинні бути звичайним текстом без спеціальних символів або форматування\n"
            "\n"
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
        url = f"{self.GEMINI_API_URL}?key={self._api_key}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code == 429:
                raise RuntimeError("Rate limit exceeded by AI service (429)")
            if resp.status_code != 200:
                raise RuntimeError(f"AI request failed ({resp.status_code}): {resp.text}")
            data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start == -1 or json_end <= 0:
            raise RuntimeError("Could not find JSON in AI response")
        json_str = text[json_start:json_end]
        extracted = json.loads(json_str)
        print(f"[extracted] Recipe: {extracted.get('name', 'Unknown')}")
        print(f"[extracted] Ingredients: {len(extracted.get('ingredients', []))} found")
        return extracted

    def to_parsed_recipe(self, extracted: Dict[str, Any]) -> schemas.ParsedRecipeFromImage:
        print(f"[converting] Converting to internal schema...")
        ingredients_out: List[schemas.ParsedIngredientFromImage] = []
        for ing in extracted.get("ingredients", []) or []:
            name = (ing.get("name") or "").strip()
            if not name:
                continue
            ingredients_out.append(
                schemas.ParsedIngredientFromImage(
                    raw_name=name,
                    quantity=_safe_parse_float(ing.get("quantity")),
                    unit=(ing.get("unit") or None),
                    preparation=None,
                    matched_ingredient_id=None,
                    matched_ingredient_name=None,
                    match_confidence=0.0,
                    match_type="unmatched",
                    needs_review=True,
                )
            )
        parsed = schemas.ParsedRecipeFromImage(
            name=(extracted.get("name") or None),
            servings=_safe_parse_int(extracted.get("servings")),
            prep_time=_safe_parse_int(extracted.get("prep_time")),
            cook_time=_safe_parse_int(extracted.get("cook_time")),
            instructions=(extracted.get("instructions") or None),
            category=(extracted.get("category") or None),
            ingredients=ingredients_out,
            nutrition=None,
            warnings=[],
            raw=extracted,
        )
        print(f"[converted] {len(parsed.ingredients)} ingredients parsed")
        return parsed

    def merge_duplicate_ingredients(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        print(f"[merging] Checking for duplicate ingredients...")
        ingredients = extracted.get("ingredients", []) or []
        if not ingredients:
            return extracted

        merged: Dict[str, Dict[str, Any]] = {}
        for ing in ingredients:
            raw_name = ing.get("name", "").strip()
            if not raw_name:
                continue

            name = _normalize_text(raw_name)
            name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
            name = name.strip()
            if not name:
                continue

            if name not in merged:
                merged[name] = {
                    "name": name,
                    "quantity": ing.get("quantity"),
                    "unit": ing.get("unit"),
                }
            else:
                print(f"  - Merging duplicate: {raw_name} into {name}")
                existing = merged[name]
                qty1 = _safe_parse_float(existing.get("quantity"))
                qty2 = _safe_parse_float(ing.get("quantity"))
                if qty1 is not None and qty2 is not None:
                    merged[name]["quantity"] = qty1 + qty2
                elif qty1 is not None:
                    merged[name]["quantity"] = qty1
                elif qty2 is not None:
                    merged[name]["quantity"] = qty2
                else:
                    merged[name]["quantity"] = None

        result = {**extracted}
        result["ingredients"] = list(merged.values())
        print(f"[merged] {len(result['ingredients'])} unique ingredients")
        return result

    async def normalize_ingredients(self, recipe: schemas.ParsedRecipeFromImage) -> schemas.ParsedRecipeFromImage:
        print(f"[normalizing] Normalizing ingredient names...")
        if not recipe.ingredients:
            return recipe

        names = [{"index": idx, "name": ing.raw_name} for idx, ing in enumerate(recipe.ingredients)]
        prompt = (
            "Нормалізуй назви інгредієнтів. Поверни лише JSON.\n"
            "Використовуй короткі назви без зайвих слів (наприклад, \"яловичина\", \"сир\", \"борошно\").\n"
            'Формат: {"results":[{"index":0,"normalized":"яловичина"}]}\n'
            f"Дані: {json.dumps(names, ensure_ascii=False)}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2048},
        }
        url = f"{self.GEMINI_API_URL}?key={self._api_key}"
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if resp.status_code != 200:
                    return recipe
                data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            json_start = text.find("{")
            json_end = text.rfind("}") + 1
            if json_start == -1 or json_end <= 0:
                return recipe
            parsed = json.loads(text[json_start:json_end])
            for item in parsed.get("results", []) or []:
                idx = item.get("index")
                normalized = item.get("normalized")
                if isinstance(idx, int) and isinstance(normalized, str) and normalized.strip():
                    print(f"  - {recipe.ingredients[idx].raw_name} → {normalized.strip()}")
                    recipe.ingredients[idx].raw_name = normalized.strip()
        except Exception as e:
            print(f"  Error normalizing: {e}")

        return recipe

    async def match_ingredients(self, recipe: schemas.ParsedRecipeFromImage, db: Session) -> schemas.ParsedRecipeFromImage:
        print(f"[matching] Matching ingredients to database...")
        matcher = _IngredientMatcher(db)
        ingredients: List[schemas.ParsedIngredientFromImage] = []
        total = max(1, len(recipe.ingredients))
        verify_pairs: List[Tuple[int, str, int, str]] = []

        for idx, ing in enumerate(recipe.ingredients):
            best = matcher.find_best_candidate(ing.raw_name)
            progress = int(((idx + 1) / total) * 100)
            self.print_step(f"matching {ing.raw_name[:30]}...", progress)

            if not best:
                ingredients.append(ing)
                print(f"  - No match found for: {ing.raw_name}")
            else:
                matched_id, matched_name, score = best
                if score >= 100.0:
                    ingredients.append(
                        _copy_parsed_ingredient(
                            ing,
                            matched_ingredient_id=matched_id,
                            matched_ingredient_name=matched_name,
                            match_confidence=1.0,
                            match_type="exact",
                            needs_review=False,
                        )
                    )
                    print(f"  ✓ Exact match: {ing.raw_name} → {matched_name} (100%)")
                elif score >= 95.0:
                    ingredients.append(
                        _copy_parsed_ingredient(
                            ing,
                            matched_ingredient_id=matched_id,
                            matched_ingredient_name=matched_name,
                            match_confidence=score / 100.0,
                            match_type="fuzzy_high",
                            needs_review=False,
                        )
                    )
                    print(f"  ✓ High confidence: {ing.raw_name} → {matched_name} ({score:.1f}%)")
                elif score >= 85.0:
                    ingredients.append(
                        _copy_parsed_ingredient(
                            ing,
                            matched_ingredient_id=matched_id,
                            matched_ingredient_name=matched_name,
                            match_confidence=score / 100.0,
                            match_type="unmatched",
                            needs_review=True,
                        )
                    )
                    verify_pairs.append((idx, ing.raw_name, matched_id, matched_name))
                    print(f"  ? Medium confidence: {ing.raw_name} → {matched_name} ({score:.1f}%) [needs review]")
                else:
                    ingredients.append(ing)
                    print(f"  - Low confidence: {ing.raw_name} → {matched_name} ({score:.1f}%) [skipped]")

        recipe.ingredients = ingredients
        return recipe, verify_pairs

    async def verify_pairs(self, pairs: List[Tuple[int, str, int, str]]) -> Dict[int, bool]:
        if not pairs:
            return {}
        print(f"[verifying] AI verification for {len(pairs)} uncertain matches...")
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
        url = f"{self.GEMINI_API_URL}?key={self._api_key}"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code != 200:
                return {}
            data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start == -1 or json_end <= 0:
            return {}
        try:
            parsed = json.loads(text[json_start:json_end])
        except json.JSONDecodeError:
            return {}
        results = {}
        for item in parsed.get("results", []) or []:
            idx = item.get("index")
            same = item.get("same")
            if isinstance(idx, int) and isinstance(same, bool):
                results[idx] = same
                print(f"  {'✓' if same else '✗'} Verified: {items[idx]['a']} == {items[idx]['b']}")
        return results

    async def estimate_nutrition(self, recipe: schemas.ParsedRecipeFromImage) -> Optional[Dict[str, float]]:
        print(f"[nutrition] Estimating nutritional values...")
        estimator = get_nutrition_estimator()
        ingredients: List[IngredientInput] = []
        for ing in recipe.ingredients:
            name = ing.matched_ingredient_name or ing.raw_name
            qty = ing.quantity if ing.quantity is not None else 0.0
            unit = ing.unit or "piece"
            ingredients.append(IngredientInput(name=name, quantity=float(qty), unit=unit))
        try:
            servings = recipe.servings or 1
            nutrition = await estimator.estimate_nutrition(ingredients, servings)
            result = {
                "calories": float(nutrition.calories),
                "protein": float(nutrition.protein),
                "carbs": float(nutrition.carbs),
                "fats": float(nutrition.fats),
            }
            print(f"  Calories: {result['calories']:.0f} kcal")
            print(f"  Protein: {result['protein']:.0f}g")
            print(f"  Carbs: {result['carbs']:.0f}g")
            print(f"  Fats: {result['fats']:.0f}g")
            return result
        except NutritionEstimationError as e:
            print(f"  Error: {e}")
            return None

    async def process(self, image_path: str) -> schemas.ParsedRecipeFromImage:
        print(f"\n{'='*60}")
        print(f"Recipe from Image Converter")
        print(f"{'='*60}")
        print(f"Input: {image_path}")

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        ext = Path(image_path).suffix.lower()
        if ext not in mime_types:
            raise ValueError(f"Unsupported image format: {ext}")
        mime_type = mime_types[ext]

        print(f"Reading image ({mime_type})...")
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        print(f"Size: {len(image_bytes) / 1024:.1f} KB")

        self.print_step("extracting", 0)
        extracted = await self.extract_recipe(image_bytes, mime_type)
        self.print_step("extracting", 100)

        self.print_step("merging", 0)
        extracted = self.merge_duplicate_ingredients(extracted)
        self.print_step("merging", 100)

        self.print_step("converting", 0)
        parsed_recipe = self.to_parsed_recipe(extracted)
        self.print_step("converting", 100)

        self.print_step("matching", 0)
        db = SessionLocal()
        try:
            parsed_recipe, verify_pairs = await self.match_ingredients(parsed_recipe, db)
        finally:
            db.close()
        self.print_step("matching", 100)

        if verify_pairs:
            self.print_step("verifying", 0)
            verified = await self.verify_pairs(verify_pairs)
            for idx, is_same in verified.items():
                if not is_same:
                    continue
                ing = parsed_recipe.ingredients[idx]
                if ing.matched_ingredient_id and ing.matched_ingredient_name:
                    parsed_recipe.ingredients[idx] = _copy_parsed_ingredient(
                        ing,
                        match_type="ai_verified",
                        needs_review=False,
                    )
            self.print_step("verifying", 100)

        self.print_step("nutrition", 0)
        parsed_recipe.nutrition = await self.estimate_nutrition(parsed_recipe)
        self.print_step("nutrition", 100)

        self.print_step("finalizing", 100)
        print(f"\n{'='*60}")
        print(f"[Final recipe JSON]")
        print(f"{'='*60}")
        return parsed_recipe


async def main():
    if len(sys.argv) < 2:
        print("Usage: python im_to_recipe.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    api_key = os.getenv("GOOGLE_AI_API_KEY")

    if not api_key:
        print("Error: GOOGLE_AI_API_KEY environment variable is not set")
        sys.exit(1)

    helper = RecipeFromImageHelper(api_key)
    recipe = await helper.process(image_path)

    print(json.dumps(recipe.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
