#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.services.recipe_import.extractors.image import ImageExtractor
from app.services.recipe_import.pipeline import RecipeImportPipeline

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
logger = logging.getLogger("im_to_recipe")

async def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python im_to_recipe.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        logger.error(f"Image not found: {image_path}")
        sys.exit(1)

    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    ext = Path(image_path).suffix.lower()
    if ext not in mime_types:
        logger.error(f"Unsupported image format: {ext}")
        sys.exit(1)
    mime_type = mime_types[ext]

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    logger.info("Extracting recipe from image...")
    extractor = ImageExtractor()
    try:
        draft = await extractor.extract(image_bytes, mime_type=mime_type)
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        sys.exit(1)

    logger.info("Processing recipe...")
    db = SessionLocal()
    try:
        pipeline = RecipeImportPipeline(db)
        
        async def progress_callback(step: str, progress: int):
            logger.info(f"[{step}] {progress}%")

        result = await pipeline.run(draft, progress_callback)
        
        # Output JSON to stdout
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
