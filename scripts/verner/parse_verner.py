#!/usr/bin/env python3
"""
Batch parse Verner recipe book pages via Gemini API.

Usage:
    python3 scripts/verner/parse_verner.py             # full run (pages 3-121)
    python3 scripts/verner/parse_verner.py --test 5    # first 5 pages (smoke test)
    python3 scripts/verner/parse_verner.py --pages 45,67  # re-run specific pages
    python3 scripts/verner/parse_verner.py --reset     # clear progress, start fresh

Outputs (written after every page):
    app/fixtures/recipes_verner.json
    app/fixtures/ingridients_verner.json
    app/fixtures/failed_verner.json   (pages that exhausted all models/retries)
    app/fixtures/parse_verner_progress.json  (resume state — do not edit manually)
"""

import argparse
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path("app/fixtures")
PAGES_DIR = BASE_DIR / "verner_pages"
PROGRESS_FILE = BASE_DIR / "parse_verner_progress.json"
RECIPES_OUT = BASE_DIR / "recipes_verner.json"
INGS_OUT = BASE_DIR / "ingridients_verner.json"
FAILED_OUT = BASE_DIR / "failed_verner.json"
ENV_PATH = ".env"

MODELS = [
    "gemini-3.1-flash-lite",  # 500 req/day — primary
    "gemini-2.5-flash-lite",  # 20 req/day  — fallback
    "gemini-2.5-flash",  # 20 req/day  — last resort
]
BACKOFF = [60, 120, 180]  # wait seconds after attempt 1, 2, 3 fail

PROMPT = """Extract the recipe from this Ukrainian recipe book page and return JSON only.

JSON schema:
{{
  "name": "recipe name in Ukrainian",
  "calories": 0,
  "protein": 0.0,
  "fats": 0.0,
  "carbs": 0.0,
  "servings": 1,
  "prep_time": 15,
  "cook_time": 30,
  "category": "Breakfast|Lunch|Dinner|Snack|Dessert|Soup|Salad|Drink",
  "dietary_tags": [],
  "breakfast_weight": 0.0,
  "lunch_weight": 0.0,
  "dinner_weight": 0.0,
  "ingredients": [
    {{"name": "ingredient name in Ukrainian", "quantity": 100.0, "unit": "g"}}
  ],
  "instructions": "full cooking instructions as a single string"
}}

Rules:
- name: recipe title from the ## heading, in Ukrainian
- calories/protein/fats/carbs: if page shows both total and per-portion (КБЖВ на 1 порцію),
  use per-portion values; otherwise use whatever values are present; source fields are
  ККАЛ / БІЛКИ / ЖИРИ / ВУГ
- category: best guess based on recipe type
- ingredients: from the "Інгредієнти" table inside the picture text blocks only;
  ignore the "заміна" (substitution) column entirely;
  unit mapping: г→"g", мл→"ml", шт→"unit", ч.л.→"tsp", ст.л.→"tbsp", to смак→0.0 qty
  for "за смаком" / "дрібка" / "за бажанням" → quantity: 0.0
- instructions: clean, readable Ukrainian reconstructed from the instructions section;
  skip "Verner" watermarks and garbled decorative characters; join continuation lines naturally
- prep_time / cook_time: estimate from context; default 15 / 30 if not stated
- servings: extract if mentioned; default 1
- breakfast_weight, lunch_weight, dinner_weight: always 0.0

TEXT:
{text}
"""


def load_key() -> str:
    for line in open(ENV_PATH):
        if "GOOGLE_AI_API_KEY" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GOOGLE_AI_API_KEY not found in .env")


def call_gemini(model: str, prompt: str, api_key: str) -> dict:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": 8192,
            },
        }
    ).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def parse_page(page_num: int, api_key: str) -> dict | None:
    page_file = PAGES_DIR / f"page_{page_num:03d}.txt"
    text = page_file.read_text(encoding="utf-8")
    prompt = PROMPT.format(text=text)

    for model in MODELS:
        for attempt in range(3):
            label = f"[page {page_num:03d}][{model}][attempt {attempt + 1}/3]"
            print(f"  {label} ...", end=" ", flush=True)
            t0 = time.time()
            try:
                resp = call_gemini(model, prompt, api_key)
                elapsed = time.time() - t0
                raw_text = resp["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(raw_text)
                tok_out = resp.get("usageMetadata", {}).get("candidatesTokenCount", "?")
                print(f"OK  {elapsed:.1f}s  {tok_out} tok")
                return parsed

            except json.JSONDecodeError as e:
                elapsed = time.time() - t0
                print(f"INVALID JSON  {elapsed:.1f}s  {e}")

            except urllib.error.HTTPError as e:
                elapsed = time.time() - t0
                body_preview = e.read().decode()[:120]
                print(f"HTTP {e.code}  {elapsed:.1f}s  {body_preview}")
                if e.code not in (429, 503):
                    break  # non-retryable → try next model immediately

            except Exception as e:
                elapsed = time.time() - t0
                print(f"ERROR  {elapsed:.1f}s  {e}")

            if attempt < 2:
                wait = BACKOFF[attempt]
                print(f"    → retry in {wait}s")
                time.sleep(wait)

        print(f"  [{model}] exhausted — trying next model")

    return None


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"done": [], "failed": [], "recipes": []}


def save_progress(progress: dict):
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2))


IMAGES_DIR = BASE_DIR / "verner_images"


def flush_outputs(recipes: list):
    """Write recipes + unique ingredient stubs derived from recipes."""
    clean = []
    for r in recipes:
        rec = {k: v for k, v in r.items() if k != "_page"}
        page = r.get("_page")
        if page:
            img = IMAGES_DIR / f"page_{page:03d}.jpg"
            if img.exists():
                rec["image_path"] = str(img)
        clean.append(rec)
    RECIPES_OUT.write_text(json.dumps(clean, ensure_ascii=False, indent=2))

    seen: set[str] = set()
    ings_out: list[dict] = []
    for recipe in recipes:
        for ing in recipe.get("ingredients", []):
            name = ing["name"].capitalize()
            if name not in seen:
                seen.add(name)
                base_unit = ing.get("unit", "g") if ing.get("unit") in ("g", "ml") else "g"
                ings_out.append(
                    {
                        "name": name,
                        "category": "Other",
                        "base_unit": base_unit,
                        "calories": 0.0,
                        "protein": 0.0,
                        "carbs": 0.0,
                        "fats": 0.0,
                    }
                )
    INGS_OUT.write_text(json.dumps(ings_out, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--test", type=int, metavar="N", help="Process only the first N pages (smoke test)"
    )
    parser.add_argument(
        "--pages", type=str, metavar="N,N,...", help="Comma-separated page numbers to (re)process"
    )
    parser.add_argument(
        "--reset", action="store_true", help="Delete progress file and start from scratch"
    )
    args = parser.parse_args()

    if args.reset and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print("Progress reset.")

    api_key = load_key()
    progress = load_progress()

    if args.pages:
        target_pages = [int(p.strip()) for p in args.pages.split(",")]
        # allow re-running failed or done pages
        for p in target_pages:
            progress["done"] = [d for d in progress["done"] if d != p]
            progress["failed"] = [f for f in progress["failed"] if f != p]
            # remove any previously stored result for this page so it gets replaced
            progress["recipes"] = [r for r in progress["recipes"] if r.get("_page") != p]
    else:
        all_pages = list(range(3, 122))
        if args.test:
            all_pages = all_pages[: args.test]
        already = set(progress["done"]) | set(progress["failed"])
        target_pages = [p for p in all_pages if p not in already]

    if not target_pages:
        print("Nothing to process — all pages already handled.")
        print(f"  done={len(progress['done'])}  failed={len(progress['failed'])}")
        return

    print(
        f"Pages to process: {len(target_pages)}  "
        f"(done so far: {len(progress['done'])}, failed: {len(progress['failed'])})"
    )

    for i, page_num in enumerate(target_pages):
        print(f"\n--- Page {page_num:03d} [{i + 1}/{len(target_pages)}] ---")
        result = parse_page(page_num, api_key)

        if result is None:
            print("  FAILED — all models exhausted")
            progress["failed"].append(page_num)
        else:
            result["_page"] = page_num  # track source page for re-run support
            progress["done"].append(page_num)
            progress["recipes"].append(result)
            print(
                f"  => {result.get('name', '(no name)')}  "
                f"| {len(result.get('ingredients', []))} ingredients  "
                f"| {result.get('calories', '?')} kcal"
            )

        save_progress(progress)
        flush_outputs(progress["recipes"])

        if result is not None and page_num != target_pages[-1]:
            time.sleep(2)  # gentle pacing between successful requests

    # write failed list
    if progress["failed"]:
        FAILED_OUT.write_text(json.dumps(progress["failed"], ensure_ascii=False, indent=2))

    print(f"\n{'=' * 60}")
    print(f"Complete.  recipes={len(progress['recipes'])}  failed={len(progress['failed'])}")
    print(f"  {RECIPES_OUT}")
    print(f"  {INGS_OUT}")
    if progress["failed"]:
        print(f"  {FAILED_OUT}  <- re-run with --pages {','.join(map(str, progress['failed']))}")


if __name__ == "__main__":
    main()
