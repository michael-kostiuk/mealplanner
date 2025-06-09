# from cmd import PROMPT
# from sqlalchemy.orm import Session
# from ..database import get_db, engine
# from .. import models
import json
import requests

import re
import json

def parse_recipe_text(text):
    """
    Parse Ukrainian recipe text to JSON format
    """
    
    # Extract recipe name
    name = text.split("КБЖВ")[0].split("Рецепт від")[0].strip().replace("\n", " ")
    # name_match = re.search(r'\*\*(.*?)\s+Рецепт', text)
    # name = name_match.group(1).strip() if name_match else "Unknown Recipe"
    
    # Extract KBZV values (calories/protein/carbs/fats)
    kbzv_match = re.search(r'КБЖВ.*?(\d+)/(\d+)/(\d+)/(\d+)', text)
    if kbzv_match:
        calories = int(kbzv_match.group(1))
        protein = int(kbzv_match.group(2))
        fats = int(kbzv_match.group(3))
        carbs = int(kbzv_match.group(4))
    else:
        calories = protein = fats = carbs = 0
    

    text.split("Інгредієнти")
    ingredients_raw = text.split("Інгредієнти")[1].split("Як готувати?")[0].strip().split("\n\n")
    ingredients_raw = [ingredient.strip() for ingredient in ingredients_raw if ingredient.strip()]
    ingridients_by_3 = []
    for i in range(2, len(ingredients_raw), 3):
        ingridients_by_3 += [ingredients_raw[i:i+3]]

    # Find ingredients section
    # ingredients_section = re.search(r'Інгредієнти.*?Як готувати\?', text, re.DOTALL)
    # if ingredients_section:
    #     ingredients_text = ingredients_section.group(0)
        
    #     # Parse each ingredient line
    #     ingredient_lines = re.findall(r'([А-Яа-яІіЇїЄє\s%]+)\s+(\d+)\s+(грам|шт)', ingredients_text)
        
    # Extract ingredients
    ingredients = []
    for ingr, count, __ in ingridients_by_3:
        ingredient_name = ingr.strip()
        quantity, unit = count.split()
        unit = "g" if unit == "грам" else "unit"
        try:
            quantity = float(quantity)
        except ValueError:
            quantity = 0.1
        
        ingredients.append({
            "name": ingredient_name.replace("\n", " "),
            "quantity": quantity,
            "unit": unit
        })
    
    # Extract cooking instructions
    instructions_match = re.search(r'Як готувати\?\s+(.*?)\*\*', text, re.DOTALL)
    instructions = ""
    if instructions_match:
        instructions_text = instructions_match.group(1).strip()
        # Clean up and format instructions
        instructions_lines = re.findall(r'\d+\.\s+([^0-9]+?)(?=\d+\.|$)', instructions_text)
        instructions = "\n".join([f"{i+1}. {line.strip()}" for i, line in enumerate(instructions_lines)])
    
    # Create JSON structure
    recipe_json = {
        "name": name,
        "servings": 1,
        "prep_time": 15,  # Default values
        "cook_time": 5,
        "instructions": instructions,
        "category": "Breakfast",
        "dietary_tags": ["vegetarian"],
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fats": fats,
        "breakfast_weight": 1.0,
        "lunch_weight": 0.2,
        "dinner_weight": 0.1,
        "ingredients": ingredients
    }
    
    return recipe_json


example = """
#####FORMAT EXAMPLE####
  {
    "name": "Overnight Oats with Banana",
    "servings": 1,
    "prep_time": 10,
    "cook_time": 0,
    "instructions": "1. Mix oats with Greek yogurt\n2. Add honey for sweetness\n3. Top with sliced banana\n4. Refrigerate overnight",
    "category": "Breakfast",
    "dietary_tags": ["vegetarian", "high_protein"],
    "calories": 385,
    "protein": 15,
    "carbs": 65,
    "fats": 8,
    "breakfast_weight": 1.0,
    "lunch_weight": 0.2,
    "dinner_weight": 0.1,
    "ingredients": [
      {"name": "Oats", "quantity": 50, "unit": "g"},
      {"name": "Greek Yogurt", "quantity": 150, "unit": "g"},
      {"name": "Banana", "quantity": 100, "unit": "g"},
      {"name": "Honey", "quantity": 15, "unit": "g"}
    ]
  }
#### END FORMAT #####
"""


class OllamaClient:
    """Client for interacting with Ollama local LLM"""
    #host.docker.internal
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "codellama:7b"):
        self.base_url = base_url
        self.model = model
        
    def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Send prompt to Ollama and get response"""
        response = None
        try:
            url = f"{self.base_url}/api/generate"
            data = {
                "model": self.model,
                "prompt": prompt,
                "stream": False
            }
            
            if system_prompt:
                data["system"] = system_prompt
                
            response = requests.post(url, json=data, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            return result.get("response", "").strip()
            
        except Exception as e:
            print(f"Error calling Ollama: {e} {response.text if response else None}")
            return f"Error: {str(e)}"

def load_fixtures():
    d  = ''
    with open("app/Книга_рецептів.txt", "rb") as f:
        d = f.read().decode('utf-8')



    dparts = d.split('')[2:]
    
    system_prompt = """convert  recipe to json in following format. do not translate. if there is no recipe in text, return empty json. reply with json only"""

    ollama = OllamaClient(model="aliafshar/gemma3-it-qat-tools:12b")

    recipes = []
    err, suc = 0, 0 
    for dpart in dparts:
        if dpart.strip() == '':
            continue
        # prompt = f"""
        # {example}

        # ############RECIPE###############
        # {dpart}
        # ############END RECIPE###############
        # """
        # print(f"executing \n\n {prompt}\n\n")
        # resp = ollama.generate(system_prompt, prompt)
        try:
            recipe = parse_recipe_text(dpart)
            name = {recipe['name']}
            # recipe = json.loads(resp)
            prompt = f"""based on name of the dish, return weight how good it would fit for meal type. max 1 least 0. and 1-3 tags unrelated to nations of origin.
dish name: {name}
""" + """
output format - json:
    { "breakfast_weight": 1.0,
        "lunch_weight": 0.2,
        "dinner_weight": 0.1,
          "dietary_tags": [
    "soup",
    "meat",
    "multi-dish"
  ]
        }"""

            resp = ollama.generate(prompt, "reply with json only")   
            try:
                resp = resp.strip("```json").strip("```")
                resp = json.loads(resp)
                recipe['breakfast_weight'] = resp['breakfast_weight']
                recipe['lunch_weight'] = resp['lunch_weight']
                recipe['dinner_weight'] = resp['dinner_weight']
                recipe['dietary_tags'] = resp['dietary_tags']
            except Exception as e:
                print(f"unexpected resp for weights: {resp}")
                recipe['breakfast_weight'] = 0.1
                recipe['lunch_weight'] = 0.2
                recipe['dinner_weight'] = 0.1
                recipe['dietary_tags'] = []


            if recipe == {}:
                continue
        except IndexError:
            err += 1
            pass
        except Exception as e:
            # raise e
            err += 1
            print(f"failed \n\n {e} \n\n {dpart[:20]}\n\n")
        else:
            suc += 1
            recipes.append(recipe)
            print(f"success: {recipe['name']}")
    
    
    print(f"success: {suc}, failed: {err}")

    # Load ingredients first
    with open('app/fixtures/recipes_al.json', 'wb') as f:
        f.write(json.dumps(recipes, indent=2, ensure_ascii=False).encode('utf-8'))
    
    ingridients = []
    for recipe in recipes:
        for ing in recipe['ingredients']:
            cats = ["Meat", "Grains","Fish","Vegetables","Dairy","Fruits","Condiments","Other"]
            prompt = f"Get category for ingridient {ing['name']}. output format: string one of [Meat, Grains,Fish,Vegetables,Dairy,Fruits,Condiments,Other]"
            resp = ollama.generate(prompt, "reply with one word") .strip()
            if resp not in cats:
                resp = "Other"
            else:
                print(f"unexpected resp: {resp}")
            ingridients.append(
                {
                "name": ing["name"],
                "category": resp,
                "base_unit": ing["unit"],
                "calories": 1.65,
                "protein": 0.31,
                "carbs": 0,
                "fats": 0.036
            })

    with open('app/fixtures/ingridients_al.json', 'wb') as f:
        f.write(json.dumps(ingridients, indent=2, ensure_ascii=False).encode('utf-8'))
    # ingredients = {}
    # for ing_data in ingredients_data:
    #     ingredient = models.Ingredient(**ing_data)
    #     db.add(ingredient)
    #     db.commit()
    #     db.refresh(ingredient)
    #     ingredients[ing_data['name']] = ingredient
    
    # # Load recipes
    # with open('app/fixtures/recipes.json', 'r') as f:
    #     recipes_data = json.load(f)
    
    # for recipe_data in recipes_data:
    #     recipe_ingredients = recipe_data.pop('ingredients')
    #     recipe = models.Recipe(**recipe_data)
    #     db.add(recipe)
    #     db.commit()
    #     db.refresh(recipe)
        
    #     for ing_data in recipe_ingredients:
    #         ing_name = ing_data.pop('name')
    #         ingredient = ingredients[ing_name]
    #         recipe_ing = models.RecipeIngredient(
    #             recipe_id=recipe.id,
    #             ingredient_id=ingredient.id,
    #             **ing_data
    #         )
    #         db.add(recipe_ing)
        
    #     db.commit()
    
if __name__ == "__main__":
    load_fixtures()