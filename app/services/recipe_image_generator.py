"""
Photo for a new recipe that was saved without one.

Gemini draws the dish in the style of the existing recipe photos: the newest recipe photo is
sent along as the style reference. The result is uploaded to Dropbox like a user's photo.
Runs in the background after the recipe is saved; any failure (no quota, no reference, a
Dropbox error) just leaves the recipe without a photo.
"""

import base64
import logging
import os
import time

import httpx
from sqlalchemy.orm import sessionmaker

from app import models
from app.core.google_ai_client import GoogleAIClient, GoogleAIError

logger = logging.getLogger(__name__)

IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")

PROMPT = (
    "Food photograph in exactly the same style, lighting, camera angle and props as the "
    "reference photo (speckled beige ceramic plate or bowl, natural linen napkin, warm wooden "
    "table, soft daylight, shallow depth of field). The dish: {name}, made with {ingredients}. "
    "Show the finished dish ready to eat. Landscape 3:2, no text, no people, no hands."
)


async def _reference_photo(session_factory: sessionmaker, recipe_id: int) -> bytes | None:
    with session_factory() as db:
        url = (
            db.query(models.Recipe.image_url)
            .filter(models.Recipe.image_url.isnot(None), models.Recipe.id != recipe_id)
            .order_by(models.Recipe.created_at.desc())
            .limit(1)
            .scalar()
        )
    if not url:
        return None
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
    return response.content if response.status_code == 200 else None


async def generate_recipe_image(
    recipe_id: int, session_factory: sessionmaker, folder: str | None = None
) -> None:
    try:
        with session_factory() as db:
            recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
            if recipe is None or recipe.image_url:
                return
            name = recipe.name
            ingredients = ", ".join(ri.ingredient.name for ri in recipe.ingredients[:12])

        parts: list[dict] = []
        reference = await _reference_photo(session_factory, recipe_id)
        if reference:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(reference).decode(),
                    }
                }
            )
        parts.append({"text": PROMPT.format(name=name, ingredients=ingredients or name)})

        result = await GoogleAIClient().generate_content(
            IMAGE_MODEL,
            {
                "contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            },
            timeout=180.0,
        )
        image = next(
            (
                p.get("inlineData") or p.get("inline_data")
                for p in result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if p.get("inlineData") or p.get("inline_data")
            ),
            None,
        )
        if image is None:
            logger.warning("Recipe %s: image model returned no image", recipe_id)
            return
        mime = image.get("mimeType") or image.get("mime_type") or "image/png"
        extension = "jpg" if "jpeg" in mime else "png"

        from app.services.dropbox_service import dropbox_service

        image_url = await dropbox_service.upload_image(
            base64.b64decode(image["data"]),
            f"{recipe_id}_{int(time.time())}_generated.{extension}",
            folder=folder,
        )
        if not image_url:
            return
        with session_factory() as db:
            recipe = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
            # The user may have added a photo of their own meanwhile; theirs wins
            if recipe is not None and not recipe.image_url:
                recipe.image_url = image_url
                db.commit()
                logger.info("Recipe %s: generated photo saved", recipe_id)
    except (GoogleAIError, httpx.HTTPError, ValueError) as exc:
        logger.warning("Recipe %s: could not generate a photo: %s", recipe_id, exc)
    except Exception:
        logger.exception("Recipe %s: photo generation failed", recipe_id)
