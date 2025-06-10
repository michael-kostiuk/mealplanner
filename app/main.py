from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import recipes, meal_plans, shopping_lists, ingredients
from .database import engine
from . import models

app = FastAPI(title="Meal Planning API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Create database tables
# models.Base.metadata.drop_all(bind=engine)
models.Base.metadata.create_all(bind=engine)

# Include routers
app.include_router(recipes.router)
app.include_router(meal_plans.router)
app.include_router(shopping_lists.router)
app.include_router(ingredients.router)
