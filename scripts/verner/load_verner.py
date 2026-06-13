#!/usr/bin/env python3
"""
Load Verner recipes and ingredients via API.

Usage:
  python scripts/verner/load_verner.py [--base-url URL]

Default URL: http://localhost:8000
For production: --base-url https://api.mplanner.online
"""

import argparse
import json
import os

import requests

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
BASE_DIR = os.path.join(BACKEND_ROOT, "app", "fixtures")

INGREDIENTS_FILE = os.path.join(BASE_DIR, "ingridients_verner.json")
RECIPES_FILE = os.path.join(BASE_DIR, "recipes_verner.json")


def normalize_name(name: str) -> str:
    return name.strip().capitalize()


def fetch_existing_ingredients(base_url: str) -> dict[str, dict]:
    resp = requests.get(f"{base_url}/ingredients/")
    resp.raise_for_status()
    return {normalize_name(ing["name"]): ing for ing in resp.json()}


def fetch_existing_recipes(base_url: str) -> dict[str, dict]:
    resp = requests.get(f"{base_url}/recipes/", params={"limit": 2000})
    resp.raise_for_status()
    return {normalize_name(r["name"]): r for r in resp.json()}


def load_ingredients(base_url: str, ingredients_data: list) -> dict[str, int]:
    print(f"\n=== Ingredients ({len(ingredients_data)} in file) ===")
    existing = fetch_existing_ingredients(base_url)
    print(f"Found {len(existing)} existing ingredients in DB")

    name_to_id: dict[str, int] = {name: ing["id"] for name, ing in existing.items()}
    created = 0
    skipped = 0

    for ing_data in ingredients_data:
        name = normalize_name(ing_data["name"])
        if name in name_to_id:
            skipped += 1
            continue

        payload = {
            "name": name,
            "category": ing_data.get("category", "Other"),
            "base_unit": ing_data.get("base_unit", "g") or "g",
            "calories": ing_data.get("calories") or 0.0,
            "protein": ing_data.get("protein") or 0.0,
            "carbs": ing_data.get("carbs") or 0.0,
            "fats": ing_data.get("fats") or 0.0,
        }
        resp = requests.post(f"{base_url}/ingredients/", json=payload)
        if resp.status_code == 200:
            ing = resp.json()
            name_to_id[name] = ing["id"]
            created += 1
            print(f"  + {name} (id={ing['id']})")
        else:
            print(f"  ERROR {name}: {resp.status_code} {resp.text[:150]}")

    print(f"Ingredients: {created} created, {skipped} already existed")
    return name_to_id


def upload_image(base_url: str, recipe_id: int, image_path: str) -> bool:
    full_path = os.path.join(BACKEND_ROOT, image_path)
    if not os.path.exists(full_path):
        print(f"    WARNING: image not found: {full_path}")
        return False

    filename = os.path.basename(full_path)
    with open(full_path, "rb") as f:
        resp = requests.post(
            f"{base_url}/recipes/{recipe_id}/upload-image",
            files={"file": (filename, f, "image/jpeg")},
        )

    if resp.status_code == 200:
        url = resp.json().get("image_url", "")
        print(f"    image -> {url}")
        return True
    else:
        print(f"    ERROR uploading image: {resp.status_code} {resp.text[:150]}")
        return False


def load_recipes(base_url: str, recipes_data: list, ingredient_map: dict[str, int]) -> None:
    print(f"\n=== Recipes ({len(recipes_data)} in file) ===")
    existing = fetch_existing_recipes(base_url)
    print(f"Found {len(existing)} existing recipes in DB")

    created = 0
    skipped = 0
    images_uploaded = 0
    errors = 0

    for recipe_data in recipes_data:
        name = normalize_name(recipe_data["name"])
        image_path = recipe_data.get("image_path")

        if name in existing:
            existing_recipe = existing[name]
            if image_path and not existing_recipe.get("image_url"):
                print(f"  ~ {name} (exists, uploading missing image)")
                if upload_image(base_url, existing_recipe["id"], image_path):
                    images_uploaded += 1
            else:
                skipped += 1
            continue

        # Map ingredient names to IDs
        recipe_ingredients = []
        for ing in recipe_data.get("ingredients", []):
            ing_name = normalize_name(ing["name"])
            ing_id = ingredient_map.get(ing_name)
            if ing_id is None:
                print(f"    SKIP unknown ingredient '{ing_name}' in '{name}'")
                continue
            unit = (ing.get("unit") or "g").strip() or "g"
            recipe_ingredients.append(
                {
                    "ingredient_id": ing_id,
                    "quantity": float(ing.get("quantity") or 0.0),
                    "unit": unit,
                }
            )

        payload = {
            "name": name,
            "calories": int(round(recipe_data.get("calories") or 0)),
            "protein": float(recipe_data.get("protein") or 0.0),
            "fats": float(recipe_data.get("fats") or 0.0),
            "carbs": float(recipe_data.get("carbs") or 0.0),
            "servings": int(recipe_data.get("servings") or 1),
            "prep_time": int(recipe_data.get("prep_time") or 0),
            "cook_time": int(recipe_data.get("cook_time") or 0),
            "category": recipe_data.get("category") or "Other",
            "instructions": recipe_data.get("instructions") or "",
            "breakfast_weight": float(recipe_data.get("breakfast_weight") or 0.0),
            "lunch_weight": float(recipe_data.get("lunch_weight") or 0.0),
            "dinner_weight": float(recipe_data.get("dinner_weight") or 0.0),
            "ingredients": recipe_ingredients,
        }

        resp = requests.post(f"{base_url}/recipes/", json=payload)
        if resp.status_code == 200:
            recipe = resp.json()
            recipe_id = recipe["id"]
            created += 1
            print(f"  + {name} (id={recipe_id}, {len(recipe_ingredients)} ingredients)")
            if image_path:
                if upload_image(base_url, recipe_id, image_path):
                    images_uploaded += 1
        else:
            errors += 1
            print(f"  ERROR '{name}': {resp.status_code} {resp.text[:300]}")

    print(
        f"\nRecipes: {created} created, {skipped} skipped, {images_uploaded} images uploaded, {errors} errors"
    )


def main():
    parser = argparse.ArgumentParser(description="Load Verner recipes and ingredients via API")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Target: {base_url}")

    with open(INGREDIENTS_FILE) as f:
        ingredients_data = json.load(f)

    with open(RECIPES_FILE) as f:
        recipes_data = json.load(f)

    ingredient_map = load_ingredients(base_url, ingredients_data)
    load_recipes(base_url, recipes_data, ingredient_map)

    print("\nDone!")


if __name__ == "__main__":
    main()
