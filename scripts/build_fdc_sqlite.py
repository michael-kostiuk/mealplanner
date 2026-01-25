#!/usr/bin/env python3
"""
Build a lightweight SQLite copy of USDA FoodData Central (Foundation + SR Legacy)
with only the fields we need for nutrition lookup. Uses only stdlib.
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
import urllib.request
import zipfile
from io import TextIOWrapper

FOUNDATION_URL = (
    "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_2025-12-18.zip"
)
FOUNDATION_PREFIX = "FoodData_Central_foundation_food_csv_2025-12-18"
SR_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"
SR_PREFIX = "FoodData_Central_sr_legacy_food_csv_2018-04"

# Nutrient IDs to pull from nutrient.csv
PROTEIN_ID = "1003"
FAT_ID = "1004"
CARB_ID = "1005"
# Energy appears as Atwater general/specific in recent dumps
ENERGY_IDS = ("2047", "2048", "1008")


def normalize(text: str) -> str:
    """Lowercase, strip accents, drop punctuation for matching/search."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def download(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urllib.request.urlretrieve(url, dest)  # nosec B310 - controlled URL


def open_csv(zip_path: str, prefix: str, filename: str) -> csv.DictReader:
    zf = zipfile.ZipFile(zip_path)
    member = f"{prefix}/{filename}"
    handle = zf.open(member)
    # TextIOWrapper keeps it streamed; caller should close ZipFile.
    return csv.DictReader(TextIOWrapper(handle, encoding="utf-8")), zf


def load_lookup(
    zip_path: str, prefix: str
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    food_rows, zf_food = open_csv(zip_path, prefix, "food.csv")
    foods = {row["fdc_id"]: row for row in food_rows}
    zf_food.close()

    nutrient_rows, zf_nutrient = open_csv(zip_path, prefix, "food_nutrient.csv")
    nutrients: dict[str, list[dict]] = {}
    for row in nutrient_rows:
        nutrients.setdefault(row["fdc_id"], []).append(row)
    zf_nutrient.close()

    portion_rows, zf_portion = open_csv(zip_path, prefix, "food_portion.csv")
    portions: dict[str, list[dict]] = {}
    for row in portion_rows:
        portions.setdefault(row["fdc_id"], []).append(row)
    zf_portion.close()

    measure_rows, zf_measure = open_csv(zip_path, prefix, "measure_unit.csv")
    measure_units = {row["id"]: row["name"] for row in measure_rows}
    zf_measure.close()

    return foods, nutrients, {"portions": portions, "measure_units": measure_units}


def pick_energy(nutrient_rows: list[dict]) -> float | None:
    nutrient_map = {row["nutrient_id"]: row for row in nutrient_rows}
    for nid in ENERGY_IDS:
        if nid in nutrient_map and nutrient_map[nid].get("amount"):
            try:
                return float(nutrient_map[nid]["amount"])
            except ValueError:
                continue
    return None


def extract_macros(nutrient_rows: list[dict]) -> dict[str, float] | None:
    nutrient_map = {row["nutrient_id"]: row for row in nutrient_rows}
    try:
        protein = float(nutrient_map[PROTEIN_ID]["amount"])
        fat = float(nutrient_map[FAT_ID]["amount"])
        carbs = float(nutrient_map[CARB_ID]["amount"])
    except (KeyError, ValueError):
        return None
    energy = pick_energy(nutrient_rows)
    if energy is None:
        return None
    return {"calories": energy, "protein": protein, "carbs": carbs, "fats": fat}


def simplify_portions(portions: list[dict], measure_units: dict[str, str]) -> list[dict]:
    simplified = []
    for p in portions:
        gram_weight = p.get("gram_weight")
        try:
            gram_weight_val = float(gram_weight) if gram_weight else None
        except ValueError:
            gram_weight_val = None
        simplified.append(
            {
                "amount": float(p["amount"]) if p.get("amount") else None,
                "measure_unit": measure_units.get(p.get("measure_unit_id", ""), ""),
                "description": p.get("portion_description") or "",
                "modifier": p.get("modifier") or "",
                "gram_weight": gram_weight_val,
            }
        )
    return simplified


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS foods (
            fdc_id INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            data_type TEXT,
            category_id INTEGER,
            calories REAL,
            protein REAL,
            carbs REAL,
            fats REAL,
            portions_json TEXT,
            search_name TEXT
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS foods_fts USING fts5(search_name, content='foods', content_rowid='fdc_id')"
    )
    conn.execute("DELETE FROM foods")
    conn.execute("DELETE FROM foods_fts")


def ingest_dataset(
    conn: sqlite3.Connection,
    foods: dict[str, dict],
    nutrients: dict[str, list[dict]],
    portions_bundle: dict[str, dict],
) -> None:
    portions = portions_bundle["portions"]
    measure_units = portions_bundle["measure_units"]
    rows = []
    fts_rows = []
    for fdc_id, food in foods.items():
        macro_rows = nutrients.get(fdc_id)
        if not macro_rows:
            continue
        macros = extract_macros(macro_rows)
        if not macros:
            continue
        portion_list = simplify_portions(portions.get(fdc_id, []), measure_units)
        description = food.get("description", "")
        search_name = normalize(description)
        rows.append(
            (
                int(fdc_id),
                description,
                food.get("data_type"),
                int(food["food_category_id"]) if food.get("food_category_id") else None,
                macros["calories"],
                macros["protein"],
                macros["carbs"],
                macros["fats"],
                json.dumps(portion_list),
                search_name,
            )
        )
        fts_rows.append((int(fdc_id), search_name))

    conn.executemany(
        """
        INSERT INTO foods (
            fdc_id, description, data_type, category_id,
            calories, protein, carbs, fats, portions_json, search_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.executemany("INSERT INTO foods_fts(rowid, search_name) VALUES (?, ?)", fts_rows)
    conn.commit()


def build_sqlite(dest: str, include_sr_legacy: bool) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        foundation_zip = os.path.join(tmpdir, "foundation.zip")
        download(FOUNDATION_URL, foundation_zip)
        foods, nutrients, portions_bundle = load_lookup(foundation_zip, FOUNDATION_PREFIX)
        sr_foods: dict[str, dict] = {}
        sr_nutrients: dict[str, list[dict]] = {}
        sr_portions_bundle: dict[str, dict] = {"portions": {}, "measure_units": {}}

        if include_sr_legacy:
            sr_zip = os.path.join(tmpdir, "sr.zip")
            download(SR_URL, sr_zip)
            sr_foods, sr_nutrients, sr_portions_bundle = load_lookup(sr_zip, SR_PREFIX)

        conn = sqlite3.connect(dest)
        create_schema(conn)
        ingest_dataset(conn, foods, nutrients, portions_bundle)
        if include_sr_legacy:
            ingest_dataset(conn, sr_foods, sr_nutrients, sr_portions_bundle)
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build SQLite FDC subset (Foundation + optional SR Legacy)."
    )
    parser.add_argument("--dest", default="data/fdc.sqlite", help="Destination path for SQLite DB")
    parser.add_argument(
        "--include-sr-legacy", action="store_true", help="Include SR Legacy data (recommended)"
    )
    args = parser.parse_args()

    dest = os.path.abspath(args.dest)
    print(f"Building FDC SQLite -> {dest}")
    build_sqlite(dest, include_sr_legacy=args.include_sr_legacy)
    print("Done.")


if __name__ == "__main__":
    main()
