import random
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models


class MealPlanGenerator:
    # Share of the daily calorie target allotted to each meal type. Used both by the
    # full-plan generator and by single-meal re-rolls so suggestions stay consistent.
    MEAL_CALORIE_FRACTIONS = {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.40, "snack": 0.15}

    def __init__(self, db: Session):
        self.db = db
        self.used_recipes: dict[int, int] = defaultdict(int)  # recipe_id -> usage count
        self.daily_calories: list[float] = []  # track calories for each day
        self.recent_recipe_ids: set[int] = set()

    def _reset_state(self) -> None:
        self.used_recipes = defaultdict(int)
        self.daily_calories = []
        self.recent_recipe_ids = set()

    def generate_meal_plan(
        self,
        start_date: datetime,
        days: int,
        target_calories: int,
        people_count: int,
        dietary_preferences: list[str],
        user_id: int,
    ) -> models.MealPlan:
        # Create meal plan
        meal_plan = models.MealPlan(
            user_id=user_id,
            start_date=start_date,
            end_date=start_date + timedelta(days=days - 1),
            people_count=people_count,
            target_calories=target_calories,
            dietary_preferences=dietary_preferences,
        )
        self.db.add(meal_plan)
        self.db.commit()
        self.db.refresh(meal_plan)

        self._reset_state()
        self._populate_entries(meal_plan)
        self.db.commit()
        self.db.refresh(meal_plan)
        return meal_plan

    def regenerate_meal_plan(self, meal_plan: models.MealPlan) -> models.MealPlan:
        self._reset_state()
        self.db.query(models.MealPlanEntry).filter(
            models.MealPlanEntry.meal_plan_id == meal_plan.id
        ).delete(synchronize_session=False)
        self._populate_entries(meal_plan)
        self.db.commit()
        self.db.refresh(meal_plan)
        return meal_plan

    def _meal_target_calories(self, meal_type: str, target_calories: int) -> float:
        return target_calories * self.MEAL_CALORIE_FRACTIONS.get(meal_type, 0.25)

    def suggest_meal(
        self,
        meal_type: str,
        target_calories: int,
        plan_recipe_ids: list[int],
        current_recipe_id: int | None = None,
    ) -> models.Recipe:
        """Pick a single replacement recipe for one meal slot (the "re-roll" action).

        Uses the same weighted-random selection as full-plan generation. The recipe
        currently in the slot is always excluded, and ``plan_recipe_ids`` (the recipes
        used in the *rest* of the plan) seed the usage counts so the max-2-uses cap is
        honoured. Calorie targeting is best-effort: it falls back to any recipe of the
        meal type if none land in the calorie band.
        """
        # Known limitation: loads full recipe table into memory. Fine for a personal
        # recipe collection; would need pagination or filtering for larger datasets.
        recipes = self.db.query(models.Recipe).all()
        if not recipes:
            raise ValueError("No recipes available")

        self._reset_state()
        for rid in plan_recipe_ids:
            if rid and rid > 0:
                self.used_recipes[rid] += 1

        exclude_ids: set[int] = set()
        if current_recipe_id and current_recipe_id > 0:
            exclude_ids.add(current_recipe_id)

        meal_target = self._meal_target_calories(meal_type, target_calories)
        return self._select_recipe(meal_type, recipes, meal_target, 0.25, exclude_ids=exclude_ids)

    def _populate_entries(self, meal_plan: models.MealPlan) -> None:
        days = (meal_plan.end_date - meal_plan.start_date).days + 1
        if days <= 0:
            raise ValueError("Invalid meal plan date range")

        # Known limitation: loads full recipe table into memory. Fine for a personal
        # recipe collection; would need pagination or filtering for larger datasets.
        recipes = self.db.query(models.Recipe).all()
        suitable_recipes = recipes  # All recipes are suitable since dietary_tags is not used

        if not suitable_recipes:
            raise ValueError("No recipes available")

        # Apply a weight penalty to recipes used in the previous week for this user
        self.recent_recipe_ids = self._load_recent_recipe_ids(
            meal_plan.user_id, meal_plan.start_date
        )

        # Generate meals for each day
        current_date = meal_plan.start_date
        for _day in range(days):
            daily_meals = self._generate_daily_meals(
                suitable_recipes, meal_plan.target_calories, current_date
            )

            # Create meal plan entries
            for meal_type, recipe in daily_meals.items():
                entry = models.MealPlanEntry(
                    meal_plan_id=meal_plan.id,
                    recipe_id=recipe.id,
                    date=current_date,
                    meal_type=meal_type,
                    servings=meal_plan.people_count,
                )
                self.db.add(entry)

            current_date += timedelta(days=1)

    def _load_recent_recipe_ids(self, user_id: int, start_date: datetime) -> set[int]:
        window_start = start_date - timedelta(days=7)
        rows = (
            self.db.query(models.MealPlanEntry.recipe_id)
            .join(models.MealPlan, models.MealPlan.id == models.MealPlanEntry.meal_plan_id)
            .filter(models.MealPlan.user_id == user_id)
            .filter(models.MealPlanEntry.date >= window_start)
            .filter(models.MealPlanEntry.date < start_date)
            .distinct()
            .all()
        )
        return {recipe_id for (recipe_id,) in rows}

    def _generate_daily_meals(
        self, recipes: list[models.Recipe], target_calories: int, date: datetime
    ) -> dict[str, models.Recipe]:
        # Calculate target calories per meal
        breakfast_target = target_calories * 0.25
        lunch_target = target_calories * 0.35

        # Select meals with calorie balancing
        selected_meals = {}

        # Select breakfast
        selected_meals["breakfast"] = self._select_recipe(
            "breakfast",
            recipes,
            breakfast_target,
            0.2,  # 20% calorie deviation allowed
        )

        # Select lunch
        selected_meals["lunch"] = self._select_recipe(
            "lunch", recipes, lunch_target, 0.2, exclude_ids={selected_meals["breakfast"].id}
        )

        # Select dinner with final calorie adjustment
        remaining_calories = target_calories - (
            selected_meals["breakfast"].calories + selected_meals["lunch"].calories
        )
        selected_meals["dinner"] = self._select_recipe(
            "dinner",
            recipes,
            remaining_calories,
            0.25,  # Allow slightly more deviation for final meal
            exclude_ids={m.id for m in selected_meals.values()},
        )

        # Track daily calories for overall balance
        daily_total = sum(meal.calories for meal in selected_meals.values())
        self.daily_calories.append(daily_total)

        return selected_meals

    def _select_recipe(
        self,
        meal_type: str,
        recipes: list[models.Recipe],
        target_calories: float,
        max_deviation: float,
        exclude_ids: set[int] | None = None,
    ) -> models.Recipe:
        if exclude_ids is None:
            exclude_ids = set()

        weight_attr = f"{meal_type}_weight"

        # Primary filter: not excluded, not overused, has meal type weight > 0
        available_recipes = [
            r
            for r in recipes
            if r.id not in exclude_ids
            and self.used_recipes[r.id] < 2
            and getattr(r, weight_attr, 0.0) > 0
        ]

        if not available_recipes:
            # Fallback 1: Allow overused recipes (used >= 2 times) but keep other constraints
            available_recipes = [
                r for r in recipes if r.id not in exclude_ids and getattr(r, weight_attr, 0.0) > 0
            ]

        if not available_recipes:
            # Fallback 2: Allow recipes with 0 weight for this meal type
            available_recipes = [
                r for r in recipes if r.id not in exclude_ids and self.used_recipes[r.id] < 2
            ]

        if not available_recipes:
            # Fallback 3: Allow any recipe not excluded today
            available_recipes = [r for r in recipes if r.id not in exclude_ids]

        if not available_recipes:
            # Fallback 4: Last resort - use any recipe at all (even if used today)
            available_recipes = list(recipes)

        if not available_recipes:
            raise ValueError(f"No available recipes for {meal_type}")

        # Try to find a recipe within the calorie range
        min_calories = target_calories * (1 - max_deviation)
        max_calories = target_calories * (1 + max_deviation)

        suitable_recipes = [
            r for r in available_recipes if min_calories <= r.calories <= max_calories
        ]

        # If no recipes match calorie constraint, use all available recipes (fallback logic from calculate_daily_meals)
        if not suitable_recipes:
            suitable_recipes = available_recipes

        # Weighted random selection
        weights = [
            getattr(r, weight_attr, 0.0) * (0.5 if r.id in self.recent_recipe_ids else 1.0)
            for r in suitable_recipes
        ]

        # Handle case where all weights are 0 (should not happen due to available_recipes filter, but safe check)
        if not weights or sum(weights) == 0:
            selected = random.choice(suitable_recipes)
        else:
            selected = random.choices(suitable_recipes, weights=weights, k=1)[0]

        # Update usage count
        self.used_recipes[selected.id] += 1
        return selected
