from sqlalchemy.orm import Session
from ..database import get_db, engine
from .. import models
import json
# D:\UNITY\mp\mealplanner\app\fixtures\ingridients.json

ING_PATH = 'app/fixtures/ingridients_al.json'
REC_PATH = 'app/fixtures/recipes_al.json'


def load_fixtures():
    db = Session(engine)
    from sqlalchemy import delete
    # q = models.Recipe.delete()
    db.execute(delete(models.Recipe))   
    # Load ingredients first
    with open(ING_PATH, 'r') as f:
        ingredients_data = json.load(f)
    
    ingredients = {}
    for ing_data in ingredients_data:
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
        print(recipe_data)
        recipe = models.Recipe(**recipe_data)
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
        
        for ing_data in recipe_ingredients:
            ing_name = ing_data.pop('name')
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