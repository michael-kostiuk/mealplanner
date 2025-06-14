import json
import re
from typing import Dict, List, Any, Optional

def parse_recipe(text: str) -> Dict[str, Any]:
    """
    Parse Ukrainian recipe text into structured JSON format.
    
    Args:
        text (str): Raw recipe text with sections like ІНГРЕДІЄНТИ, СПОСІБ ПРИГОТУВАННЯ, ККАЛ
    
    Returns:
        Dict[str, Any]: Structured recipe data
    """
    lines = [line.strip() for line in text.strip().split('\n')]
    lines = [line for line in lines if line]  # Remove empty lines
    
    recipe = {
        "name": "",
        "servings": 1,
        "prep_time": 15,  # Default values
        "cook_time": 5,
        "instructions": "",
        "category": "Main",
        "dietary_tags": [],
        "calories": 0,
        "protein": 0,
        "carbs": 0,
        "fats": 0,
        "breakfast_weight": 0.3,
        "lunch_weight": 0.5,
        "dinner_weight": 0.2,
        "ingredients": []
    }
    
    # Extract recipe name (first line)
    if lines:
        recipe["name"] = lines[0]
    
    # Find section boundaries
    sections = {}
    current_section = None
    section_content = []
    
    for i, line in enumerate(lines[1:], 1):  # Skip first line (name)
        # Check if line is a section header
        if line.upper() in ['ІНГРЕДІЄНТИ:', 'СПОСІБ ПРИГОТУВАННЯ:', 'ККАЛ'] or \
           line.endswith('ККАЛ') or line.upper().startswith('ІНГРЕДІЄНТИ') or \
           line.upper().startswith('СПОСІБ'):
            
            # Save previous section
            if current_section and section_content:
                sections[current_section] = section_content.copy()
            
            # Start new section
            current_section = line.upper().replace(':', '').strip()
            section_content = []
        else:
            # Add content to current section
            if current_section:
                section_content.append(line)
    
    # Don't forget the last section
    if current_section and section_content:
        sections[current_section] = section_content.copy()
    
    # Parse ingredients
    if 'ІНГРЕДІЄНТИ' in sections:
        recipe["ingredients"] = parse_ingredients(sections['ІНГРЕДІЄНТИ'])
    
    # Parse instructions
    if 'СПОСІБ ПРИГОТУВАННЯ' in sections:
        recipe["instructions"] = parse_instructions(sections['СПОСІБ ПРИГОТУВАННЯ'])
    
    # Parse nutrition info
    calories_section = None
    for key in sections.keys():
        if 'ККАЛ' in key:
            calories_section = key
            break
    
    if calories_section and sections[calories_section]:
        nutrition = parse_nutrition(sections[calories_section])
        recipe.update(nutrition)
    
    return recipe

def parse_ingredients(ingredient_lines: List[str]) -> List[Dict[str, Any]]:
    """Parse ingredient lines into structured format."""
    ingredients = []
    
    for line in ingredient_lines:
        if not line.strip():
            continue
            
        ingredient = parse_single_ingredient(line)
        if ingredient:
            ingredients.append(ingredient)
    
    return ingredients

def parse_single_ingredient(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single ingredient line."""
    line = line.strip()
    if not line:
        return None
    
    # Try to extract quantity and unit
    # Look for patterns like "олія 5г", "яйця 2 шт", "помідор 150г"
    quantity = 1.0
    unit = "unit"
    name = line
    
    # Check for weight patterns (numbers followed by г, кг, мл, л)
    weight_pattern = r'(\d+(?:\.\d+)?)\s*(г|кг|мл|л)'
    weight_match = re.search(weight_pattern, line)
    
    if weight_match:
        quantity = float(weight_match.group(1))
        unit_text = weight_match.group(2)
        unit = "g" if unit_text == "г" else unit_text
        name = line.replace(weight_match.group(0), '').strip()
    else:
        # Check for count patterns (numbers followed by шт)
        count_pattern = r'(\d+)\s*шт'
        count_match = re.search(count_pattern, line)
        
        if count_match:
            quantity = float(count_match.group(1))
            unit = "unit"
            name = line.replace(count_match.group(0), '').strip()
    
    # Clean up name
    name = name.strip()
    if not name:
        name = line  # Fallback to original line
    
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit
    }

def parse_instructions(instruction_lines: List[str]) -> str:
    """Parse instruction lines into formatted text."""
    # Join all instruction lines
    full_text = ' '.join(instruction_lines)
    
    # Split by sentence indicators and number the steps
    sentences = []
    current_sentence = ""
    
    for char in full_text:
        current_sentence += char
        if char == '.' and len(current_sentence.strip()) > 10:
            sentences.append(current_sentence.strip())
            current_sentence = ""
    
    # Add remaining text if any
    if current_sentence.strip():
        sentences.append(current_sentence.strip())
    
    # Filter out very short sentences and number the steps
    numbered_steps = []
    step_num = 1
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 15:  # Only include substantial sentences
            numbered_steps.append(f"{step_num}. {sentence}")
            step_num += 1
    
    return '\n'.join(numbered_steps)

def parse_nutrition(nutrition_lines: List[str]) -> Dict[str, int]:
    """Parse nutrition information."""
    nutrition = {
        "calories": 0,
        "protein": 0,
        "fats": 0,
        "carbs": 0
    }
    
    # Combine all nutrition lines into one text
    nutrition_text = ' '.join(nutrition_lines)
    
    # Extract calories
    cal_match = re.search(r'(\d+)\s*ККАЛ', nutrition_text)
    if cal_match:
        nutrition["calories"] = int(cal_match.group(1))
    
    # Extract macros - look for "білки", "жири", "вуглеводи"
    protein_match = re.search(r'білки\s*(\d+)', nutrition_text)
    if protein_match:
        nutrition["protein"] = int(protein_match.group(1))
    
    fat_match = re.search(r'жири\s*(\d+)', nutrition_text)
    if fat_match:
        nutrition["fats"] = int(fat_match.group(1))
    
    carb_match = re.search(r'вуглеводи\s*(\d+)', nutrition_text)
    if carb_match:
        nutrition["carbs"] = int(carb_match.group(1))
    
    return nutrition

def load_fixtures():
    d  = ''
    with open("recipes2.txt", "rb") as f:
        d = f.read().decode('utf-8')

    dparts = d.split('')[2:]
    
    system_prompt = """convert  recipe to json in following format. do not translate. if there is no recipe in text, return empty json. reply with json only"""

    # ollama = OllamaClient(model="aliafshar/gemma3-it-qat-tools:12b")

    recipes = []
    err, suc = 0, 0 
    for dpart in dparts:
        if dpart.strip() == '':
            continue

        try:
            recipe = parse_recipe(dpart)
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

            # resp = ollama.generate(prompt, "reply with json only")   
            # try:
            #     resp = resp.strip("```json").strip("```")
            #     resp = json.loads(resp)
            #     recipe['breakfast_weight'] = resp['breakfast_weight']
            #     recipe['lunch_weight'] = resp['lunch_weight']
            #     recipe['dinner_weight'] = resp['dinner_weight']
            #     recipe['dietary_tags'] = resp['dietary_tags']
            # except Exception as e:
            #     print(f"unexpected resp for weights: {resp}")
            #     recipe['breakfast_weight'] = 0.1
            #     recipe['lunch_weight'] = 0.2
            #     recipe['dinner_weight'] = 0.1
            #     recipe['dietary_tags'] = []


            if recipe == {}:
                continue
        except IndexError:
            err += 1
            pass
        except Exception as e:
            # raise e
            err += 1
            repr = dpart.replace('\n', ' ')[:20]
            print(f"failed \n\n {e} \n\n {repr}\n\n")
        else:
            suc += 1
            recipes.append(recipe)
            print(f"success: {recipe['name']}")
    
    
    print(f"success: {suc}, failed: {err}")

    # Load ingredients first
    with open('app/fixtures/recipes2.json', 'wb') as f:
        f.write(json.dumps(recipes, indent=2, ensure_ascii=False).encode('utf-8'))
    
    ingridients = []
    for recipe in recipes:
        for ing in recipe['ingredients']:
            cats = ["Meat", "Grains","Fish","Vegetables","Dairy","Fruits","Condiments","Other"]
            # prompt = f"Get category for ingridient {ing['name']}. output format: string one of [Meat, Grains,Fish,Vegetables,Dairy,Fruits,Condiments,Other]"
            # resp = ollama.generate(prompt, "reply with one word") .strip()
            resp = ''
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

    with open('app/fixtures/ingridients2.json', 'wb') as f:
        f.write(json.dumps(ingridients, indent=2, ensure_ascii=False).encode('utf-8'))


if __name__ == "__main__":
    load_fixtures()