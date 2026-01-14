from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .routers import recipes, meal_plans, shopping_lists, ingredients, nutrition
from .database import engine
from . import models

import os
import logging
import sys
import time
from logging import StreamHandler
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text


class DockerCompatibleHandler(StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[DockerCompatibleHandler()],
    force=True
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
# NOTE: Using sys.stdout.write() instead of logging module here because uvicorn's
# async middleware context blocks logging module output to stdout. The logging module
# works correctly in other contexts (e.g., alembic migrations show logs),
# but middleware requires direct stdout writes with explicit flush for Docker.
async def log_requests(request: Request, call_next):
    start_time = time.time()

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    sys.stdout.write(f"{timestamp} - app.main - INFO - Request: {request.method} {request.url.path}\n")
    sys.stdout.flush()

    try:
        response = await call_next(request)

        process_time = time.time() - start_time
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        sys.stdout.write(f"{timestamp} - app.main - INFO - Response: {request.method} {request.url.path} - Status: {response.status_code} - {process_time:.3f}s\n")
        sys.stdout.flush()

        return response
    except Exception as e:
        process_time = time.time() - start_time
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        sys.stdout.write(f"{timestamp} - app.main - ERROR - Error: {request.method} {request.url.path} - {process_time:.3f}s - {type(e).__name__}: {str(e)}\n")
        sys.stdout.flush()
        import traceback
        traceback.print_exc()
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

@app.on_event("startup")
def startup_event():
    run_migrations()

# Include routers
app.include_router(recipes.router)
app.include_router(meal_plans.router)
app.include_router(shopping_lists.router)
app.include_router(ingredients.router)
app.include_router(nutrition.router)
