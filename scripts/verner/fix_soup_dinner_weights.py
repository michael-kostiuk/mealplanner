"""
Set meal weights for recipes in recipes_verner.json based on sections from page_002.txt.
Edit SECTION_WEIGHTS below, then run from project root:
  python scripts/verner/fix_soup_dinner_weights.py
"""

import json
import re
from difflib import get_close_matches

PAGE_PATH = "app/fixtures/verner_pages/page_002.txt"
JSON_PATH = "app/fixtures/recipes_verner.json"

# Edit weights here: (breakfast_weight, lunch_weight, dinner_weight)
SECTION_WEIGHTS = {
    "сніданки": (0.3, 0.0, 0.0),  # breakfasts
    "перекуси": (0.0, 0.0, 0.0),  # snacks
    "десерти": (0.0, 0.0, 0.0),  # desserts
    "перші_страви": (0.0, 0.5, 0.0),  # soups / first courses — dinner forced 0
    "основні_страви": (0.0, 0.3, 0.3),  # main dishes
    "фастфуд": (0.0, 0.4, 0.2),  # fast food
    "напої": (0.0, 0.0, 0.0),  # drinks
    "салати": (0.0, 0.3, 0.3),  # salads
    "пісні_страви": (0.0, 0.1, 0.2),  # lean / vegan dishes
}

# Section headers as they appear in the page (order matters for slicing)
SECTION_HEADERS = [
    ("сніданки", "# сніданки:"),
    ("перекуси", "перекуси:"),
    ("десерти", "дЕСЕРТИ"),
    ("перші_страви", "перші страви"),
    ("основні_страви", "основні страви"),
    ("фастфуд", "Фастфуд"),
    ("напої", "напої"),
    ("салати", "салати"),
    ("пісні_страви", "пісні страви"),
]

# Matches nutritional data block: "316,8 / 10,8 / 13,4 / 50,4"
NUTRITION_RE = re.compile(r"\d[\d,]*\s*/\s*\d[\d,]*\s*/\s*\d[\d,]*\s*/\s*\d[\d,]*")


def parse_sections():
    with open(PAGE_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    text = lines[20].strip()  # line 21 (1-indexed) has all content

    positions = []
    for key, header in SECTION_HEADERS:
        pos = text.find(header)
        if pos >= 0:
            positions.append((pos, key, header))
    positions.sort()

    section_recipes = {}
    for i, (pos, key, header) in enumerate(positions):
        start = pos + len(header)
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk = text[start:end]

        parts = NUTRITION_RE.split(chunk)
        names = []
        for part in parts[:-1]:
            name = re.sub(r"^[\s\-–—()\d,.]+", "", part).strip()
            name = re.sub(r"\s+", " ", name)
            if len(name) > 2:
                names.append(name)
        section_recipes[key] = names

    return section_recipes


def main():
    section_recipes = parse_sections()

    for section, names in section_recipes.items():
        print(f"[{section}] {len(names)} recipes")

    name_to_section = {
        name.lower(): section for section, names in section_recipes.items() for name in names
    }
    all_page_names = list(name_to_section.keys())

    with open(JSON_PATH, encoding="utf-8") as f:
        recipes = json.load(f)

    unmatched = []
    for r in recipes:
        matches = get_close_matches(r["name"].lower(), all_page_names, n=1, cutoff=0.5)
        if not matches:
            unmatched.append(r["name"])
            continue
        section = name_to_section[matches[0]]
        b, lw, d = SECTION_WEIGHTS[section]
        # soups never get dinner weight regardless of what's set above
        if section == "перші_страви":
            d = 0.0
        r["breakfast_weight"] = b
        r["lunch_weight"] = lw
        r["dinner_weight"] = d

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(recipes, f, ensure_ascii=False, indent=2)

    print(f"\nUpdated {len(recipes) - len(unmatched)}/{len(recipes)} recipes.")
    if unmatched:
        print(f"Unmatched (fill manually): {unmatched}")


if __name__ == "__main__":
    main()
