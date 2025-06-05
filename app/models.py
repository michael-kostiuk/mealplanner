from datetime import datetime
from typing import List
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Table, JSON
from sqlalchemy.orm import relationship, DeclarativeBase

class Base(DeclarativeBase):
    pass

class Recipe(Base):
    __tablename__ = 'recipes'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    servings = Column(Integer, nullable=False)
    prep_time = Column(Integer)  # in minutes
    cook_time = Column(Integer)  # in minutes
    instructions = Column(String, nullable=False)
    category = Column(String(100))
    dietary_tags = Column(JSON)  # Array of dietary tags
    
    # Nutritional information
    calories = Column(Integer)
    protein = Column(Float)
    carbs = Column(Float)
    fats = Column(Float)
    
    # Meal type suitability weights (0-1)
    breakfast_weight = Column(Float, default=0.0)
    lunch_weight = Column(Float, default=0.0)
    dinner_weight = Column(Float, default=0.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    ingredients = relationship('RecipeIngredient', back_populates='recipe')
    meal_plan_entries = relationship('MealPlanEntry', back_populates='recipe')

class Ingredient(Base):
    __tablename__ = 'ingredients'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100))  # for shopping list organization
    base_unit = Column(String(50))  # base unit for nutritional info
    
    # Nutritional information per base unit
    calories = Column(Float)
    protein = Column(Float)
    carbs = Column(Float)
    fats = Column(Float)
    
    recipes = relationship('RecipeIngredient', back_populates='ingredient')

class RecipeIngredient(Base):
    __tablename__ = 'recipe_ingredients'
    
    recipe_id = Column(Integer, ForeignKey('recipes.id'), primary_key=True)
    ingredient_id = Column(Integer, ForeignKey('ingredients.id'), primary_key=True)
    quantity = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    
    recipe = relationship('Recipe', back_populates='ingredients')
    ingredient = relationship('Ingredient', back_populates='recipes')

class MealPlan(Base):
    __tablename__ = 'meal_plans'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    people_count = Column(Integer, default=1)
    target_calories = Column(Integer)
    dietary_preferences = Column(JSON)  # Array of dietary preferences
    created_at = Column(DateTime, default=datetime.utcnow)
    
    entries = relationship('MealPlanEntry', back_populates='meal_plan')
    shopping_lists = relationship('ShoppingList', back_populates='meal_plan')
    user = relationship('User', back_populates='meal_plans')

class MealPlanEntry(Base):
    __tablename__ = 'meal_plan_entries'
    
    id = Column(Integer, primary_key=True)
    meal_plan_id = Column(Integer, ForeignKey('meal_plans.id'))
    recipe_id = Column(Integer, ForeignKey('recipes.id'))
    date = Column(DateTime, nullable=False)
    meal_type = Column(String(50))  # breakfast, lunch, dinner
    servings = Column(Integer, default=1)
    
    meal_plan = relationship('MealPlan', back_populates='entries')
    recipe = relationship('Recipe', back_populates='meal_plan_entries')

class ShoppingList(Base):
    __tablename__ = 'shopping_lists'
    
    id = Column(Integer, primary_key=True)
    meal_plan_id = Column(Integer, ForeignKey('meal_plans.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default='active')  # active, exported, completed
    export_format = Column(String(50))  # ios_reminders, pdf, etc.
    
    items = relationship('ShoppingListItem', back_populates='shopping_list')
    meal_plan = relationship('MealPlan', back_populates='shopping_lists')

class ShoppingListItem(Base):
    __tablename__ = 'shopping_list_items'
    
    id = Column(Integer, primary_key=True)
    shopping_list_id = Column(Integer, ForeignKey('shopping_lists.id'))
    ingredient_id = Column(Integer, ForeignKey('ingredients.id'))
    quantity = Column(Float)
    unit = Column(String(50))
    category = Column(String(100))  # inherited from ingredient for organization
    status = Column(String(50), default='pending')  # pending, purchased
    
    shopping_list = relationship('ShoppingList', back_populates='items')
    ingredient = relationship('Ingredient')

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    calorie_target = Column(Integer)
    dietary_preferences = Column(String)
    
    meal_plans = relationship('MealPlan', back_populates='user')