import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from alembic import command
from alembic.config import Config

from .database import engine
from .logging_setup import setup_logging
from .routers import health, ingredients, meal_plans, nutrition, recipes, shopping_lists

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Meal Planning API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()

    logger.info(f"Request: {request.method} {request.url.path}")

    try:
        response = await call_next(request)

        process_time = time.time() - start_time
        logger.info(
            f"Response: {request.method} {request.url.path} - Status: {response.status_code} - {process_time:.3f}s"
        )

        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(
            f"Error: {request.method} {request.url.path} - {process_time:.3f}s - {type(e).__name__}: {str(e)}",
            exc_info=True,
        )
        raise


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
        logger.info("Detected existing database without migrations. Stamping head...")
        command.stamp(alembic_cfg, "head")

    logger.info("Running database migrations...")
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migrations completed.")


@app.on_event("startup")
def startup_event():
    run_migrations()
    # Re-apply logging setup in case Alembic or Uvicorn messed it up
    setup_logging()
    logger.info("Application startup completed. Logging verified.")


# Include routers
app.include_router(recipes.router)
app.include_router(meal_plans.router)
app.include_router(shopping_lists.router)
app.include_router(ingredients.router)
app.include_router(nutrition.router)
app.include_router(health.router)
