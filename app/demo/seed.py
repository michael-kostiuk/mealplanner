from sqlalchemy.orm import Session

from .. import models
from ..auth.deps import DEMO_USER_ID

DEMO_EMAIL = "demo@mplanner.online"


def _columns(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


# id, created_at and foreign keys are not part of the seed format
_INGREDIENT_FIELDS = _columns(models.Ingredient) - {"id"}
_PORTION_FIELDS = _columns(models.IngredientPortion) - {"id", "ingredient_id"}
_RECIPE_FIELDS = _columns(models.Recipe) - {"id", "created_at"}
_RECIPE_INGREDIENT_FIELDS = _columns(models.RecipeIngredient) - {"recipe_id", "ingredient_id"}


def _check_keys(item: dict, allowed: set[str], extra: set[str], what: str) -> None:
    unknown = set(item) - allowed - extra
    if unknown:
        raise ValueError(f"Unknown {what} keys in demo seed: {sorted(unknown)}")


def load_seed(db: Session, seed: dict) -> None:
    """Populate an empty demo DB: demo user, then ingredients (with portions), then recipes."""
    db.add(models.User(id=DEMO_USER_ID, email=DEMO_EMAIL))

    ingredients_by_key: dict[str, models.Ingredient] = {}
    for item in seed.get("ingredients", []):
        _check_keys(item, _INGREDIENT_FIELDS, {"key", "portions"}, "ingredient")
        ingredient = models.Ingredient(**{k: item[k] for k in _INGREDIENT_FIELDS & set(item)})
        for portion in item.get("portions", []):
            _check_keys(portion, _PORTION_FIELDS, set(), "portion")
            ingredient.portions.append(models.IngredientPortion(**portion))
        db.add(ingredient)
        ingredients_by_key[str(item["key"])] = ingredient

    for item in seed.get("recipes", []):
        _check_keys(item, _RECIPE_FIELDS, {"ingredients"}, "recipe")
        recipe = models.Recipe(**{k: item[k] for k in _RECIPE_FIELDS & set(item)})
        for link in item.get("ingredients", []):
            _check_keys(link, _RECIPE_INGREDIENT_FIELDS, {"ingredient_key"}, "recipe ingredient")
            ingredient = ingredients_by_key[str(link["ingredient_key"])]
            recipe.ingredients.append(
                models.RecipeIngredient(
                    ingredient=ingredient,
                    **{k: link[k] for k in _RECIPE_INGREDIENT_FIELDS & set(link)},
                )
            )
        db.add(recipe)

    db.commit()
