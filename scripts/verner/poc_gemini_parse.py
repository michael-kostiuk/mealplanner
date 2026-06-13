"""
POC: compare free Gemini models on a single recipe page.
Run: python3 scripts/verner/poc_gemini_parse.py
"""

import json
import time
import urllib.request
import urllib.error

# --- config ---
ENV_PATH = ".env"
PAGE_FILES = [
    "app/fixtures/verner_pages/page_050.txt",  # complex: multi-line ingredients, garbled text
]
MODELS = [
    "gemini-3.1-flash-lite",
    "gemma-4-31b-it",
]


def load_key():
    for line in open(ENV_PATH):
        if "GOOGLE_AI_API_KEY" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GOOGLE_AI_API_KEY not found in .env")


def call_gemini(model, prompt, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
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
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


PROMPT_TEMPLATE = """Extract the recipe from this text and return JSON only.

JSON format:
{{
  "name": "recipe name in Ukrainian",
  "calories": 0,
  "protein": 0.0,
  "fats": 0.0,
  "carbs": 0.0,
  "servings": 1,
  "prep_time": 15,
  "cook_time": 10,
  "category": "Breakfast|Lunch|Dinner|Snack|Dessert|Soup|Salad|Drink",
  "ingredients": [
    {{"name": "ingredient name", "quantity": 100.0, "unit": "g|ml|unit|tsp|tbsp"}}
  ],
  "instructions": "full cooking instructions as single string"
}}

Rules:
- calories/protein/fats/carbs: from ККАЛ/БІЛКИ/ЖИРИ/ВУГ
- ingredients: from the ----- picture text ----- blocks (ignore substitution/заміна column)
- unit: "g" for г, "ml" for мл, "unit" for шт, "tsp" for ч.л., "tbsp" for ст.л.
- instructions: clean readable Ukrainian, ignore garbled characters

TEXT:
{text}
"""

api_key = load_key()

for page_file in PAGE_FILES:
    raw = open(page_file, encoding="utf-8").read()
    prompt = PROMPT_TEMPLATE.format(text=raw)
    print(f"\n{'#' * 60}")
    print(f"PAGE: {page_file}  ({len(raw)} chars)")
    print(f"{'#' * 60}")

    for model in MODELS:
        print(f"{'=' * 60}")
        print(f"MODEL: {model}")
        print(f"{'=' * 60}")
        t0 = time.time()
        try:
            resp = call_gemini(model, prompt, api_key)
            elapsed = time.time() - t0

            usage = resp.get("usageMetadata", {})
            in_tok = usage.get("promptTokenCount", "?")
            out_tok = usage.get("candidatesTokenCount", "?")

            raw_text = resp["candidates"][0]["content"]["parts"][0]["text"]
            speed = f"{out_tok / elapsed:.0f} tok/s" if isinstance(out_tok, int) else "?"
            print(f"Time: {elapsed:.1f}s  |  tokens in={in_tok} out={out_tok}  |  speed={speed}")

            try:
                parsed = json.loads(raw_text)
                print("JSON: VALID ✓")
                print(f"  name:        {parsed.get('name')}")
                print(
                    f"  kcal/p/f/c:  {parsed.get('calories')} / {parsed.get('protein')} / {parsed.get('fats')} / {parsed.get('carbs')}"
                )
                print(f"  ingredients: {len(parsed.get('ingredients', []))} items")
                for ing in parsed.get("ingredients", []):
                    print(f"    - {ing.get('name'):30s} {ing.get('quantity')} {ing.get('unit')}")
                instr = parsed.get("instructions", "")
                print(f"  instructions ({len(instr)} chars): {instr[:120]}...")
            except json.JSONDecodeError as e:
                print(f"JSON: INVALID ✗ ({e})")
                print(raw_text[:400])

        except urllib.error.HTTPError as e:
            elapsed = time.time() - t0
            print(f"HTTP {e.code} after {elapsed:.1f}s: {e.read().decode()[:200]}")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"ERROR after {elapsed:.1f}s: {e}")
        print()
        time.sleep(3)  # avoid rate limit between calls
