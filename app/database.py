import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")

# Known issue: sync engine used with async route handlers. Blocking DB calls inside
# async def routes will stall the event loop under concurrent load. Fix: switch to
# create_async_engine + AsyncSession, or change DB-only routes to plain def so
# FastAPI runs them in a threadpool. Deprioritised — single-user app, no concurrency concern.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=900,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
