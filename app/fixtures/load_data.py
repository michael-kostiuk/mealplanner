import json

from sqlalchemy.orm import Session

from .. import models
from ..database import engine

# D:\UNITY\mp\mealplanner\app\fixtures\ingridients.json

ING_PATH = ["app/fixtures/ingridients_al.json", "app/fixtures/ingridients2.json", "app/fixtures/ingridients_verner.json"]
REC_PATH = [
    "app/fixtures/recipes_al.json",
    "app/fixtures/recipes2.json",
    "app/fixtures/recipes_verner.json",
]
# ING_PATH = 'app/fixtures/ingridients2.json'
# REC_PATH = 'app/fixtures/recipes2.json'


def load_fixtures():
    db = Session(engine)

    # Load ingredients first
    ingredients_data = []
    for ing_path in ING_PATH:
        with open(ing_path) as f:
            ingredients_data += json.load(f)

    names = [x["name"] for x in ingredients_data]
    db_query = db.query(models.Ingredient)
    # db_query = db_query.filter(any_([models.Ingredient.name.ilike(f"%{name}%") for name in names]))

    ingredients = {}
    for exists in db_query.all():
        ingredients[exists.name.capitalize()] = exists

    ingredients = {}
    for ing_data in ingredients_data:
        ing_data["name"] = ing_data["name"].capitalize()
        if ing_data["name"] in ingredients:
            continue
        ingredient = models.Ingredient(**ing_data)
        db.add(ingredient)
        db.commit()
        db.refresh(ingredient)
        ingredients[ing_data["name"]] = ingredient

    # Load recipes
    recipes_data = []
    for rec_path in REC_PATH:
        with open(rec_path) as f:
            recipes_data += json.load(f)

    db_query = db.query(models.Recipe)
    # db_query = db_query.filter(any_([models.Ingredient.name.ilike(f"%{name}%") for name in names]))

    recipes_all = {}
    for exists in db_query.all():
        recipes_all[exists.name.capitalize()] = exists

    model_columns = {c.key for c in models.Recipe.__table__.columns}

    for recipe_data in recipes_data:
        recipe_ingredients = recipe_data.pop("ingredients")
        recipe_data.pop("dietary_tags", None)
        recipe_data.pop("image_path", None)
        recipe_data = {k: v for k, v in recipe_data.items() if k in model_columns}
        recipe_data["name"] = recipe_data["name"].capitalize()
        if recipe_data["name"] in recipes_all:
            recipe = recipes_all[recipe_data["name"]]
            for k, v in recipe_data.items():
                setattr(recipe, k, v)
        else:
            recipe = models.Recipe(**recipe_data)
        db.add(recipe)
        db.commit()
        db.refresh(recipe)

        for ing_data in recipe_ingredients:
            ing_name = ing_data.pop("name").capitalize()
            ingredient = ingredients.get(ing_name)
            if ingredient is None:
                print(f"  SKIP unknown ingredient: {ing_name!r} (recipe: {recipe_data['name']})")
                continue
            recipe_ing = models.RecipeIngredient(
                recipe_id=recipe.id, ingredient_id=ingredient.id, **ing_data
            )
            db.add(recipe_ing)

        db.commit()

    db.close()


if __name__ == "__main__":
    load_fixtures()
