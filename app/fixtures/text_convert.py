import re
import json

def parse_recipe_text(text):
    """
    Parse Ukrainian recipe text to JSON format
    """
    
    # Extract recipe name
    name_match = re.search(r'\*\*(.*?)\s+Рецепт', text)
    name = name_match.group(1).strip() if name_match else "Unknown Recipe"
    
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
    print("st1: ",ingredients_raw)
    ingridients_by_3 = []
    for i in range(2, len(ingredients_raw), 3):
        ingridients_by_3 += [ingredients_raw[i:i+3]]
    print("st2: ",ingridients_by_3)
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
        quantity = int(quantity)
        
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

# Test with the provided text
text = """
Ліниві
вареники
з вишнею
Рецепт від нашого куратора
Аліни

КБЖВ

Оригінального рецепту
(без замін) на всю порцію:
543/41/15/45
Інгредієнти

Кількість

Заміна

Яйце

1 шт

Немає альтернативи

Творог 5%

200 грам

Немає альтернативи

Вишня

200 грам

Інші ягоди

Борошно
цільнозернове

20 грам

Будь-яке інше борошно

Борошно
цільнозернове
для обкатки

10 грам

Будь-яке інше борошно

Як готувати?
1. Борошно 20 грам, яйце, творог змішати в одну масу.
2. Мокрими руками зліпити з маси кульки.
3. Всередину кожної кульки поміщаємо вишню і обкатуємо кульку
в борошні.
4. Кладемо кульки в киплячу воду і після того, як вони спливуть,
варимо ще 2 хвилини.
"""
# Parse and print result
result = parse_recipe_text(text)
print(json.dumps(result, ensure_ascii=False, indent=2))