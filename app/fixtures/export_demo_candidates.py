"""Read-only export of production recipes for building the English demo seed.

Reads PROD_DATABASE_URL from .env, opens the connection read-only and writes:
  data/demo_raw.json        all recipes in the demo seed format (still in the original language)
  data/demo_candidates.md   proposed subset for the owner to review

Usage: python app/fixtures/export_demo_candidates.py
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PER_MEAL = 12  # top recipes per meal type
MEALS = ("breakfast", "lunch", "dinner")

RECIPE_COLS = (
    "name servings prep_time cook_time instructions category calories protein carbs fats "
    "image_url breakfast_weight lunch_weight dinner_weight"
).split()
INGREDIENT_COLS = "name category base_unit fdc_id calories protein carbs fats".split()
PORTION_COLS = "unit gram_weight modifier is_default".split()


def rows(conn, sql: str) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(sql))]


def main() -> None:
    load_dotenv(ROOT / ".env")
    url = os.environ["PROD_DATABASE_URL"]
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})

    with engine.connect() as conn:
        conn.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))
        recipes = rows(conn, f"SELECT id, {', '.join(RECIPE_COLS)} FROM recipes ORDER BY id")
        links = rows(
            conn, "SELECT recipe_id, ingredient_id, quantity, unit FROM recipe_ingredients"
        )
        ingredients = rows(
            conn, f"SELECT id, {', '.join(INGREDIENT_COLS)} FROM ingredients ORDER BY id"
        )
        portions = rows(
            conn, f"SELECT ingredient_id, {', '.join(PORTION_COLS)} FROM ingredient_portions"
        )
        plan_owners = rows(
            conn, "SELECT user_id, count(*) AS n FROM meal_plans GROUP BY user_id ORDER BY user_id"
        )
        fav_owners = rows(
            conn, "SELECT user_id, count(*) AS n FROM favorites GROUP BY user_id ORDER BY user_id"
        )
        users = rows(conn, "SELECT id FROM users ORDER BY id")

    used = {link["ingredient_id"] for link in links}
    portions_by_ing: dict[int, list[dict]] = {}
    for p in portions:
        portions_by_ing.setdefault(p["ingredient_id"], []).append({k: p[k] for k in PORTION_COLS})

    seed_ingredients = []
    for ing in ingredients:
        if ing["id"] not in used:
            continue
        item = {"key": str(ing["id"]), **{k: ing[k] for k in INGREDIENT_COLS}}
        item["portions"] = portions_by_ing.get(ing["id"], [])
        seed_ingredients.append(item)

    links_by_recipe: dict[int, list[dict]] = {}
    for link in links:
        links_by_recipe.setdefault(link["recipe_id"], []).append(
            {
                "ingredient_key": str(link["ingredient_id"]),
                "quantity": link["quantity"],
                "unit": link["unit"],
            }
        )

    seed_recipes = []
    for r in recipes:
        item = {"source_id": r["id"], **{k: r[k] for k in RECIPE_COLS}}
        # the API schema requires both times
        item["prep_time"] = item["prep_time"] or 0
        item["cook_time"] = item["cook_time"] or 0
        item["ingredients"] = links_by_recipe.get(r["id"], [])
        seed_recipes.append(item)

    DATA.mkdir(exist_ok=True)
    raw = {"ingredients": seed_ingredients, "recipes": seed_recipes}
    (DATA / "demo_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2))

    # candidates: top PER_MEAL per meal type, image first, then highest weight
    def w(r, meal):
        return r[f"{meal}_weight"] or 0.0

    chosen: dict[int, dict] = {}
    per_meal_count = {}
    for meal in MEALS:
        ranked = sorted(
            (r for r in recipes if w(r, meal) > 0),
            key=lambda r: (not r["image_url"], -w(r, meal), r["id"]),
        )[:PER_MEAL]
        per_meal_count[meal] = len(ranked)
        for r in ranked:
            chosen[r["id"]] = r
    ordered = sorted(chosen.values(), key=lambda r: (not r["image_url"], r["id"]))

    def cell(v):
        return str(v if v is not None else "").replace("|", "/").replace("\n", " ")

    lines = [
        f"# Demo seed candidates ({len(ordered)} of {len(recipes)} recipes)",
        "",
        "| id | name | category | breakfast | lunch | dinner | calories | image |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in ordered:
        lines.append(
            f"| {r['id']} | {cell(r['name'])} | {cell(r['category'])} "
            f"| {w(r, 'breakfast'):g} | {w(r, 'lunch'):g} | {w(r, 'dinner'):g} "
            f"| {cell(r['calories'])} | {'yes' if r['image_url'] else 'no'} |"
        )
    lines += ["", "## Other recipes not proposed", ""]
    for r in recipes:
        if r["id"] not in chosen:
            lines.append(f"- {r['id']}: {r['name']}")
    (DATA / "demo_candidates.md").write_text("\n".join(lines) + "\n")

    print(f"recipes: {len(recipes)}, ingredients used: {len(seed_ingredients)}")
    print(
        f"candidates: {len(ordered)}; per meal type (weight > 0, top {PER_MEAL}): {per_meal_count}"
    )
    print("meal_plans by user_id:", [(o["user_id"], o["n"]) for o in plan_owners])
    print("favorites by user_id:", [(o["user_id"], o["n"]) for o in fav_owners])
    print(
        "users ids:",
        [u["id"] for u in users],
        "| user id 1 exists:",
        any(u["id"] == 1 for u in users),
    )


if __name__ == "__main__":
    main()
