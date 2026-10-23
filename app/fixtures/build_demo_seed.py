"""Build app/demo/seed.json from data/demo_raw.json, approved ids and English translations.

Usage:
  python app/fixtures/build_demo_seed.py --approved 2,6,7 --translations data/translate/out/
Translation files: {"recipes": {"<source_id>": {name, category, instructions}},
                    "ingredients": {"<key>": {name, category}}}
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import models  # noqa: E402
from app.demo.seed import load_seed  # noqa: E402
from app.units import normalize_unit  # noqa: E402

CYRILLIC = re.compile("[\u0400-\u04ff]")
# values normalize_unit does not know; "to смак" is a mangled "to taste"
UNIT_OVERRIDES = {"дрібка": "pinch", "смак": "to taste", "to смак": "to taste"}


def canonical_unit(value):
    if value is None:
        return None
    unit = normalize_unit(value) or UNIT_OVERRIDES.get(str(value).strip().lower())
    if not unit:
        sys.exit(f"Cannot normalise unit {value!r}")
    return unit


def normalise_units(seed: dict) -> None:
    for r in seed["recipes"]:
        for link in r["ingredients"]:
            link["unit"] = canonical_unit(link["unit"])
    for ing in seed["ingredients"]:
        if ing.get("base_unit"):
            ing["base_unit"] = canonical_unit(ing["base_unit"])
        for portion in ing.get("portions", []):
            portion["unit"] = canonical_unit(portion["unit"])


def assert_no_cyrillic(node, path="seed") -> None:
    if isinstance(node, str):
        if CYRILLIC.search(node):
            sys.exit(f"Cyrillic left in {path}: {node[:60]!r}")
    elif isinstance(node, dict):
        for k, v in node.items():
            assert_no_cyrillic(k, f"{path}.{k}")
            assert_no_cyrillic(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            assert_no_cyrillic(v, f"{path}[{i}]")


def load_translations(spec: str) -> tuple[dict, dict]:
    p = Path(spec)
    paths = sorted(p.glob("*.json")) if p.is_dir() else sorted(Path(x) for x in glob.glob(spec))
    if not paths:
        sys.exit(f"No translation files match {spec}")
    recipes: dict[str, dict] = {}
    ingredients: dict[str, dict] = {}
    for path in paths:
        data = json.loads(path.read_text())
        for k, v in data.get("recipes", {}).items():
            recipes.setdefault(str(k), v)
        for k, v in data.get("ingredients", {}).items():
            ingredients.setdefault(str(k), v)  # first translation wins
    return recipes, ingredients


def build(raw: dict, approved: set[int], recipe_tr: dict, ing_tr: dict) -> dict:
    recipes = [r for r in raw["recipes"] if r["source_id"] in approved]
    missing = approved - {r["source_id"] for r in recipes}
    if missing:
        sys.exit(f"Approved ids not in raw export: {sorted(missing)}")

    out_recipes = []
    for r in recipes:
        tr = recipe_tr.get(str(r["source_id"]))
        if not tr:
            sys.exit(f"Missing translation for recipe {r['source_id']}")
        item = {k: v for k, v in r.items() if k != "source_id"}
        for field in ("name", "category", "instructions"):
            if not tr.get(field):
                sys.exit(f"Recipe {r['source_id']}: translation lacks {field}")
            item[field] = tr[field]
        out_recipes.append(item)

    used = {link["ingredient_key"] for r in out_recipes for link in r["ingredients"]}
    out_ings = []
    for ing in raw["ingredients"]:
        if ing["key"] not in used:
            continue
        tr = ing_tr.get(ing["key"])
        if not tr or not tr.get("name"):
            sys.exit(f"Missing translation for ingredient {ing['key']} ({ing['name']})")
        item = dict(ing)
        item["name"] = tr["name"]
        if ing.get("category"):
            item["category"] = tr.get("category") or ing["category"]
        out_ings.append(item)
    return {"ingredients": out_ings, "recipes": out_recipes}


def validate(seed: dict) -> None:
    """Load the seed into a throwaway in-memory SQLite DB; raises on any bad key/reference."""
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        load_seed(db, seed)
        n = db.query(models.Recipe).count()
    if n != len(seed["recipes"]):
        sys.exit(f"Validation: loaded {n} recipes, expected {len(seed['recipes'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved", required=True, help="comma separated recipe ids")
    ap.add_argument("--translations", required=True, help="directory or glob of JSON files")
    ap.add_argument("--raw", default=str(ROOT / "data" / "demo_raw.json"))
    ap.add_argument("--out", default=str(ROOT / "app" / "demo" / "seed.json"))
    args = ap.parse_args()

    approved = {int(x) for x in args.approved.split(",") if x.strip()}
    raw = json.loads(Path(args.raw).read_text())
    recipe_tr, ing_tr = load_translations(args.translations)
    seed = build(raw, approved, recipe_tr, ing_tr)
    normalise_units(seed)
    assert_no_cyrillic(seed)
    validate(seed)
    Path(args.out).write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n")
    print(
        f"wrote {args.out}: {len(seed['recipes'])} recipes, {len(seed['ingredients'])} ingredients"
    )


if __name__ == "__main__":
    main()
