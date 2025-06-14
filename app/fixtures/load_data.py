from sqlalchemy.orm import Session
from sqlalchemy import any_
from ..database import get_db, engine
from .. import models
import json
# D:\UNITY\mp\mealplanner\app\fixtures\ingridients.json

# ING_PATH = 'app/fixtures/ingridients_al.json'
# REC_PATH = 'app/fixtures/recipes_al.json'
ING_PATH = 'app/fixtures/ingridients2.json'
REC_PATH = 'app/fixtures/recipes2.json'

def load_fixtures():
    db = Session(engine)
    from sqlalchemy import delete
    # q = models.Recipe.delete()
    db.execute(delete(models.Recipe))   
    # Load ingredients first
    with open(ING_PATH, 'r') as f:
        ingredients_data = json.load(f)
    
    names = [x['name'] for x in ingredients_data]
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
        ingredients[ing_data['name']] = ingredient
    
    # Load recipes
    with open(REC_PATH, 'r') as f:
        recipes_data = json.load(f)

    for recipe_data in recipes_data:
        recipe_ingredients = recipe_data.pop('ingredients')
        # print(recipe_data)
        recipe = models.Recipe(**recipe_data)
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
        
        for ing_data in recipe_ingredients:
            ing_name = ing_data.pop('name').capitalize()
            ingredient = ingredients[ing_name]
            recipe_ing = models.RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                **ing_data
            )
            db.add(recipe_ing)
        
        db.commit()
    
    db.close()

if __name__ == "__main__":
    load_fixtures()