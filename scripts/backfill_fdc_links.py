#!/usr/bin/env python3
"""Backfill FDC links and portions for existing ingredients.

This is intentionally a separate script (not part of Alembic migrations) so
migrations remain schema-only and don't import/run application services.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add backend root to import path
sys.path.insert(0, str(Path(__file__).parent.parent))


from app import models
from app.database import SessionLocal
from app.services.fdc_linker import link_ingredient_to_fdc, link_ingredient_to_fdc_async

logger = logging.getLogger("backfill_fdc_links")


async def _link_async(
    ingredient: models.Ingredient,
    db,
    min_confidence: float,
) -> bool:
    return await link_ingredient_to_fdc_async(ingredient, db, min_confidence=min_confidence)


def _iter_ingredients(db, limit: int | None):
    query = (
        db.query(models.Ingredient)
        .filter(models.Ingredient.fdc_id.is_(None))
        .order_by(models.Ingredient.id)
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ingredient fdc_id and portions.")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.85,
        help="Minimum confidence to link (default: 0.85)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of ingredients to process",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=50,
        help="Commit after N successful links (default: 50)",
    )
    parser.add_argument(
        "--use-ai",
        action="store_true",
        help="Use async translator-based linking for non-English names",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without committing changes",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    db = SessionLocal()
    loop: asyncio.AbstractEventLoop | None = None
    try:
        ingredients = _iter_ingredients(db, args.limit)
        logger.info("Found %d unlinked ingredients", len(ingredients))

        linked = 0
        skipped = 0
        failed = 0
        since_commit = 0

        if args.use_ai:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for ingredient in ingredients:
            # Skip if already has portions (avoid duplicates)
            if ingredient.portions:
                skipped += 1
                continue

            try:
                ok = False
                if args.use_ai:
                    if loop is None:
                        raise RuntimeError("Async loop not initialized")
                    ok = bool(
                        loop.run_until_complete(_link_async(ingredient, db, args.min_confidence))
                    )
                else:
                    ok = bool(
                        link_ingredient_to_fdc(ingredient, db, min_confidence=args.min_confidence)
                    )

                if not ok:
                    skipped += 1
                    continue

                linked += 1
                since_commit += 1

                if not args.dry_run and since_commit >= args.commit_every:
                    db.commit()
                    since_commit = 0
            except Exception as exc:
                failed += 1
                db.rollback()
                logger.warning(
                    "Failed to link ingredient %s (%s): %s", ingredient.id, ingredient.name, exc
                )

        if args.dry_run:
            db.rollback()
            logger.info("Dry-run complete. Linked=%d Skipped=%d Failed=%d", linked, skipped, failed)
            return 0

        db.commit()
        logger.info("Backfill complete. Linked=%d Skipped=%d Failed=%d", linked, skipped, failed)
        return 0
    finally:
        try:
            if loop is not None:
                loop.close()
        finally:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
