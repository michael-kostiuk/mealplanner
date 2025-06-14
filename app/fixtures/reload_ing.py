import json

def main():
    with open('app/fixtures/recipes2.json', 'rb') as f:
        recipes = json.loads(f.read().decode('utf-8'))
    
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
    main()