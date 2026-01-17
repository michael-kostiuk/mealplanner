import asyncio
import base64
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

import httpx
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import SessionLocal
from .nutrition_estimator import IngredientInput, NutritionEstimationError, get_nutrition_estimator

RECIPE_EXTRACTION_PROMPT_UA = (
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


class _JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, schemas.RecipeFromImageJob] = {}
        self._cancel: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval_s = 300

    def _ensure_cleanup_task(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval_s)
                async with self._lock:
                    self._cleanup_locked()
        except asyncio.CancelledError:
            return

    async def create(self, job_id: str) -> schemas.RecipeFromImageJob:
        self._ensure_cleanup_task()
        async with self._lock:
            now = _utcnow()
            job = schemas.RecipeFromImageJob(
                id=job_id,
                status="queued",
                current_step="",
                step_progress=0,
                overall_progress=0,
                result=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = job
            self._cancel[job_id] = asyncio.Event()
            return job

    async def get(self, job_id: str) -> Optional[schemas.RecipeFromImageJob]:
        self._ensure_cleanup_task()
        async with self._lock:
            return self._jobs.get(job_id)

    async def update(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        current_step: Optional[str] = None,
        step_progress: Optional[int] = None,
        overall_progress: Optional[int] = None,
        result: Optional[schemas.ParsedRecipeFromImage] = None,
        error: Optional[str] = None,
    ) -> None:
        self._ensure_cleanup_task()
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            data = job.model_dump()
            if status is not None:
                data["status"] = status
            if current_step is not None:
                data["current_step"] = current_step
            if step_progress is not None:
                data["step_progress"] = max(0, min(100, int(step_progress)))
            if overall_progress is not None:
                data["overall_progress"] = max(0, min(100, int(overall_progress)))
            if result is not None:
                data["result"] = result
            if error is not None:
                data["error"] = error
            data["updated_at"] = _utcnow()
            self._jobs[job_id] = schemas.RecipeFromImageJob(**data)

    async def cancel(self, job_id: str) -> bool:
        self._ensure_cleanup_task()
        async with self._lock:
            evt = self._cancel.get(job_id)
            if not evt:
                return False
            evt.set()
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in ("completed", "failed", "canceled"):
                return True
            data = job.model_dump()
            data["status"] = "canceled"
            data["updated_at"] = _utcnow()
            self._jobs[job_id] = schemas.RecipeFromImageJob(**data)
            return True

    async def is_canceled(self, job_id: str) -> bool:
        self._ensure_cleanup_task()
        async with self._lock:
            evt = self._cancel.get(job_id)
            return bool(evt and evt.is_set())

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow().timestamp() - 3600
        to_delete = [jid for jid, job in self._jobs.items() if job.created_at.timestamp() < cutoff]
        for jid in to_delete:
            self._jobs.pop(jid, None)
            self._cancel.pop(jid, None)


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


class RecipeFromImageService:
    DEFAULT_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemma-3-27b-it:generateContent"

    def __init__(self) -> None:
        self._api_key = os.getenv("GOOGLE_AI_API_KEY")
        self._api_url = os.getenv("GEMINI_API_URL", self.DEFAULT_GEMINI_API_URL)
        self._jobs = _JobStore()

    async def start_job(self, image_bytes: bytes, mime_type: str) -> schemas.RecipeFromImageStartResponse:
        job_id = f"rfi_{int(time.time())}_{os.urandom(6).hex()}"
        await self._jobs.create(job_id)
        asyncio.create_task(self._run_job(job_id, image_bytes, mime_type))
        return schemas.RecipeFromImageStartResponse(job_id=job_id)

    async def get_job(self, job_id: str) -> Optional[schemas.RecipeFromImageJob]:
        return await self._jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        return await self._jobs.cancel(job_id)

    async def _run_job(self, job_id: str, image_bytes: bytes, mime_type: str) -> None:
        await self._jobs.update(job_id, status="processing", current_step="extracting", step_progress=0, overall_progress=0)
        if not self._api_key:
            await self._jobs.update(job_id, status="failed", error="GOOGLE_AI_API_KEY environment variable is not set")
            return

        db: Optional[Session] = None
        try:
            db = SessionLocal()
            if await self._jobs.is_canceled(job_id):
                return

            extracted = await self._extract_recipe(image_bytes=image_bytes, mime_type=mime_type)
            await self._jobs.update(job_id, current_step="extracting", step_progress=100, overall_progress=40)
            if await self._jobs.is_canceled(job_id):
                return

            extracted = self._merge_duplicate_ingredients(extracted)
            parsed_recipe = self._to_parsed_recipe(extracted)
            await self._jobs.update(job_id, current_step="matching", step_progress=0, overall_progress=50)
            if await self._jobs.is_canceled(job_id):
                return

            matcher = _IngredientMatcher(db)
            ingredients: List[schemas.ParsedIngredientFromImage] = []
            total = max(1, len(parsed_recipe.ingredients))
            verify_pairs: List[Tuple[int, str, int, str]] = []

            for idx, ing in enumerate(parsed_recipe.ingredients):
                if await self._jobs.is_canceled(job_id):
                    return
                best = matcher.find_best_candidate(ing.raw_name)
                if not best:
                    ingredients.append(ing)
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
                    else:
                        ingredients.append(ing)

                step = int(((idx + 1) / total) * 100)
                overall = 55 + int(((idx + 1) / total) * 25)
                await self._jobs.update(job_id, current_step="matching", step_progress=step, overall_progress=overall)

            if verify_pairs and not await self._jobs.is_canceled(job_id):
                await self._jobs.update(job_id, current_step="verifying", step_progress=0, overall_progress=80)
                verified = await self._verify_pairs(verify_pairs)
                for idx, is_same in verified.items():
                    if not is_same:
                        continue
                    ing = ingredients[idx]
                    if ing.matched_ingredient_id and ing.matched_ingredient_name:
                        ingredients[idx] = _copy_parsed_ingredient(
                            ing,
                            match_type="ai_verified",
                            needs_review=False,
                        )
                await self._jobs.update(job_id, current_step="verifying", step_progress=100, overall_progress=85)

            parsed_recipe.ingredients = ingredients
            await self._jobs.update(job_id, current_step="nutrition", step_progress=0, overall_progress=86)
            if not await self._jobs.is_canceled(job_id):
                parsed_recipe.nutrition = await self._estimate_nutrition(parsed_recipe)
            await self._jobs.update(job_id, current_step="finalizing", step_progress=100, overall_progress=100)
            await self._jobs.update(job_id, status="completed", result=parsed_recipe)
        except Exception as e:
            await self._jobs.update(job_id, status="failed", error=str(e))
        finally:
            if db is not None:
                db.close()

    async def _extract_recipe(self, *, image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
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
        url = f"{self._api_url}?key={self._api_key}"
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
        return json.loads(json_str)

    def _to_parsed_recipe(self, extracted: Dict[str, Any]) -> schemas.ParsedRecipeFromImage:
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
        return schemas.ParsedRecipeFromImage(
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

    def _merge_duplicate_ingredients(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        import re
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
                    "name": raw_name,
                    "quantity": ing.get("quantity"),
                    "unit": ing.get("unit"),
                }
            else:
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
        return result

    async def _normalize_ingredients(self, recipe: schemas.ParsedRecipeFromImage) -> schemas.ParsedRecipeFromImage:
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
                    recipe.ingredients[idx].raw_name = normalized.strip()
        except Exception:
            pass

        return recipe

    async def _verify_pairs(self, pairs: List[Tuple[int, str, int, str]]) -> Dict[int, bool]:
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
            if resp.status_code == 429:
                return {}
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
        return results

    async def _estimate_nutrition(self, recipe: schemas.ParsedRecipeFromImage) -> Optional[Dict[str, float]]:
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
            return {
                "calories": float(nutrition.calories),
                "protein": float(nutrition.protein),
                "carbs": float(nutrition.carbs),
                "fats": float(nutrition.fats),
            }
        except NutritionEstimationError:
            return None


recipe_from_image_service = RecipeFromImageService()
