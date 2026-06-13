"""
POC: time + quality test of Ollama gemma4:26b parsing a single recipe page.
Run: python scripts/verner/poc_ollama_parse.py
"""

import json
import time
import urllib.request

OLLAMA_URL = "http://10.0.2.2:11434/api/generate"
MODEL = "gemma4:26b"
PAGE_FILE = "app/fixtures/verner_pages/page_003.txt"

with open(PAGE_FILE, encoding="utf-8") as f:
    raw = f.read()

prompt = f"""Extract the recipe from this text and return JSON only. No explanation.

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
- calories/protein/fats/carbs: extract from ККАЛ/БІЛКИ/ЖИРИ/ВУГ fields
- ingredients: extract from the table inside ----- picture text ----- blocks
- instructions: clean text, ignore garbled characters, reconstruct readable Ukrainian
- unit: use "g" for г/грам, "ml" for мл, "unit" for шт, "tsp" for ч.л., "tbsp" for ст.л.
- ignore substitution (заміна) column

TEXT:
{raw}
"""

payload = json.dumps(
    {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"num_predict": 2048},
    }
).encode()

print(f"Sending page to {MODEL}...")
t0 = time.time()

req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=300) as resp:
    result = json.load(resp)

elapsed = time.time() - t0
response_text = result.get("response", "")

print(f"\nTime: {elapsed:.1f}s")
print(
    f"Tokens: prompt={result.get('prompt_eval_count', '?')}  response={result.get('eval_count', '?')}"
)
print(f"Speed: {result.get('eval_count', 0) / elapsed:.1f} tok/s")
print("\n--- PARSED RESULT ---")
try:
    parsed = json.loads(response_text)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
except json.JSONDecodeError:
    print("NOT VALID JSON:")
    print(response_text)
