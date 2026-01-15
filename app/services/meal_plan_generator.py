from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from collections import defaultdict
import random
from .. import models, schemas

class MealPlanGenerator:
    def __init__(self, db: Session):
        self.db = db
        self.used_recipes: Dict[int, int] = defaultdict(int)  # recipe_id -> usage count
        self.daily_calories: List[float] = []  # track calories for each day

    def generate_meal_plan(
        self,
        start_date: datetime,
        days: int,
        target_calories: int,
        people_count: int,
        dietary_preferences: List[str],
        user_id: int
    ) -> models.MealPlan:
        # Create meal plan
        meal_plan = models.MealPlan(
            user_id=user_id,
            start_date=start_date,
            end_date=start_date + timedelta(days=days - 1),
            people_count=people_count,
            target_calories=target_calories,
            dietary_preferences=dietary_preferences
        )
        self.db.add(meal_plan)
        self.db.commit()
        self.db.refresh(meal_plan)

        # Get all suitable recipes
        recipes = self.db.query(models.Recipe).all()
        suitable_recipes = recipes  # All recipes are suitable since dietary_tags is not used

        if not suitable_recipes:
            raise ValueError("No recipes available")

        # Generate meals for each day
        current_date = start_date
        for day in range(days):
            daily_meals = self._generate_daily_meals(
                suitable_recipes,
                target_calories,
                current_date
            )

            # Create meal plan entries
            for meal_type, recipe in daily_meals.items():
                entry = models.MealPlanEntry(
                    meal_plan_id=meal_plan.id,
                    recipe_id=recipe.id,
                    date=current_date,
                    meal_type=meal_type,
                    servings=people_count
                )
                self.db.add(entry)

            current_date += timedelta(days=1)

        self.db.commit()
        self.db.refresh(meal_plan)
        return meal_plan

    def _generate_daily_meals(self, recipes: List[models.Recipe], target_calories: int, date: datetime) -> Dict[str, models.Recipe]:
        # Filter recipes by usage count
        available_recipes = self._filter_available_recipes(recipes)

        # Calculate target calories per meal
        breakfast_target = target_calories * 0.25
        lunch_target = target_calories * 0.35
        dinner_target = target_calories * 0.40

        # Select meals with calorie balancing
        selected_meals = {}
        
        # Select breakfast
        selected_meals['breakfast'] = self._select_recipe(
            'breakfast',
            available_recipes,
            breakfast_target,
            0.2  # 20% calorie deviation allowed
        )

        # Select lunch
        selected_meals['lunch'] = self._select_recipe(
            'lunch',
            available_recipes,
            lunch_target,
            0.2,
            exclude_ids={selected_meals['breakfast'].id}
        )

        # Select dinner with final calorie adjustment
        remaining_calories = target_calories - (
            selected_meals['breakfast'].calories +
            selected_meals['lunch'].calories
        )
        selected_meals['dinner'] = self._select_recipe(
            'dinner',
            available_recipes,
            remaining_calories,
            0.25,  # Allow slightly more deviation for final meal
            exclude_ids={m.id for m in selected_meals.values()}
        )

        # Track daily calories for overall balance
        daily_total = sum(meal.calories for meal in selected_meals.values())
        self.daily_calories.append(daily_total)

        return selected_meals

    def _filter_available_recipes(
        self,
        recipes: List[models.Recipe]
    ) -> List[models.Recipe]:
        # Filter out recipes used twice already
        return [r for r in recipes if self.used_recipes[r.id] < 2]

    def _select_recipe(
        self,
        meal_type: str,
        recipes: List[models.Recipe],
        target_calories: float,
        max_deviation: float,
        exclude_ids: Set[int] = None
    ) -> models.Recipe:
        if exclude_ids is None:
            exclude_ids = set()

        weight_attr = f'{meal_type}_weight'
        # Filter out excluded recipes and recipes with 0 weight for this meal type
        available_recipes = [r for r in recipes if r.id not in exclude_ids and getattr(r, weight_attr) > 0]

        if not available_recipes:
            # If no recipes available (e.g. all used or weight 0), try to find any recipe not excluded
            # ignoring the weight requirement if absolutely necessary, or just fail.
            # But usually we want to respect meal types.
            # If we strictly enforce weight > 0, we might run out.
            # For now, let's raise error or return None? The previous code would crash on min() on empty sequence.
            # Let's try to be robust: if strict meal type not found, try any available recipe?
            # But "Dinner" should probably not be a "Breakfast" only recipe.
            raise ValueError(f"No available recipes for {meal_type}")

        # Try to find a recipe within the calorie range
        min_calories = target_calories * (1 - max_deviation)
        max_calories = target_calories * (1 + max_deviation)

        suitable_recipes = [
            r for r in available_recipes
            if min_calories <= r.calories <= max_calories
        ]
        
        # If no recipes match calorie constraint, use all available recipes (fallback logic from calculate_daily_meals)
        if not suitable_recipes:
            suitable_recipes = available_recipes

        # Weighted random selection
        weights = [getattr(r, weight_attr) for r in suitable_recipes]
        
        # Handle case where all weights are 0 (should not happen due to available_recipes filter, but safe check)
        if not weights or sum(weights) == 0:
             selected = random.choice(suitable_recipes)
        else:
             selected = random.choices(suitable_recipes, weights=weights, k=1)[0]

        # Update usage count
        self.used_recipes[selected.id] += 1
        return selected