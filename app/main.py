from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import recipes, meal_plans, shopping_lists, ingredients, nutrition
from .database import engine
from . import models

import os
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

app = FastAPI(title="Meal Planning API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

def run_migrations():
    # Ensure we are in the root directory where alembic.ini is located
    # This might depend on how the app is run. Assuming CWD is project root.
    alembic_cfg = Config("alembic.ini")
    
    # Check if database is already initialized but not versioned
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    should_stamp = False
    if "recipes" in existing_tables:
        if "alembic_version" not in existing_tables:
            should_stamp = True
        else:
            # Check if table is empty
            with engine.connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if version is None:
                    should_stamp = True
    
    if should_stamp:
        print("Detected existing database without migrations. Stamping head...")
        command.stamp(alembic_cfg, "head")
    
    print("Running database migrations...")
    command.upgrade(alembic_cfg, "head")

@app.on_event("startup")
def startup_event():
    run_migrations()

# Include routers
app.include_router(recipes.router)
app.include_router(meal_plans.router)
app.include_router(shopping_lists.router)
app.include_router(ingredients.router)
app.include_router(nutrition.router)
