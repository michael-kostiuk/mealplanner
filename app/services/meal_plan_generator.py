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
            end_date=start_date + timedelta(days=days),
            people_count=people_count,
            target_calories=target_calories,
            dietary_preferences=dietary_preferences
        )
        self.db.add(meal_plan)
        self.db.commit()
        self.db.refresh(meal_plan)

        # Get all suitable recipes
        recipes = self.db.query(models.Recipe).all()
        suitable_recipes = [r for r in recipes 
                          if all(pref in r.dietary_tags for pref in dietary_preferences) or not dietary_preferences]

        if not suitable_recipes:
            raise ValueError("No recipes available matching dietary preferences")

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
        # Sort recipes by meal type weights
        breakfast_recipes = self._filter_and_sort_recipes(recipes, 'breakfast_weight')
        lunch_recipes = self._filter_and_sort_recipes(recipes, 'lunch_weight')
        dinner_recipes = self._filter_and_sort_recipes(recipes, 'dinner_weight')

        # Calculate target calories per meal
        breakfast_target = target_calories * 0.25
        lunch_target = target_calories * 0.35
        dinner_target = target_calories * 0.40

        # Select meals with calorie balancing
        selected_meals = {}
        
        # Select breakfast
        selected_meals['breakfast'] = self._select_recipe(
            'breakfast',
            breakfast_recipes,
            breakfast_target,
            0.2  # 20% calorie deviation allowed
        )

        # Select lunch
        selected_meals['lunch'] = self._select_recipe(
            'lunch',
            lunch_recipes,
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
            dinner_recipes,
            remaining_calories,
            0.25,  # Allow slightly more deviation for final meal
            exclude_ids={m.id for m in selected_meals.values()}
        )

        # Track daily calories for overall balance
        daily_total = sum(meal.calories for meal in selected_meals.values())
        self.daily_calories.append(daily_total)

        return selected_meals

    def _filter_and_sort_recipes(
        self,
        recipes: List[models.Recipe],
        weight_attr: str
    ) -> List[models.Recipe]:
        # Filter out recipes used twice already
        available_recipes = [r for r in recipes if self.used_recipes[r.id] < 2]
        # Sort by weight and randomize within weight groups
        return sorted(
            available_recipes,
            key=lambda x: (getattr(x, weight_attr) * random.uniform(0.8, 1.2)),
            reverse=True
        )

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
        # Filter out excluded recipes
        available_recipes = [r for r in recipes if r.id not in exclude_ids and getattr(r, weight_attr) > 0]

        # Try to find a recipe within the calorie range
        min_calories = target_calories * (1 - max_deviation)
        max_calories = target_calories * (1 + max_deviation)

        suitable_recipes = [
            r for r in available_recipes
            if min_calories <= r.calories <= max_calories
        ]
        weights = [getattr(r, weight_attr) for r in suitable_recipes]

        if suitable_recipes:
            selected = random.choices(suitable_recipes, weights=weights, k=1)[0]
        else:
            # If no recipe in range, select the closest one
            selected = min(available_recipes,
                          key=lambda r: abs(r.calories - target_calories))

        # Update usage count
        self.used_recipes[selected.id] += 1
        return selected