import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os
import sys

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import Base
from sqlalchemy.engine.url import make_url

# Use a test database URL. 
# We will assume we can create a database named 'test_db' on the same host.
# The original URL is likely postgresql://postgres:postgres@dbmp:5432/postgres
# We want postgresql://postgres:postgres@dbmp:5432/test_db

ORIGINAL_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@dbmp:5432/postgres")
TEST_DATABASE_URL = "postgresql://postgres:postgres@dbmp:5432/test_db"

@pytest.fixture(scope="session")
def db_engine():
    # Connect to default DB to create test DB
    # isolation_level="AUTOCOMMIT" is required to CREATE DATABASE
    default_engine = create_engine(ORIGINAL_DATABASE_URL, isolation_level="AUTOCOMMIT")
    
    try:
        with default_engine.connect() as conn:
            # Terminate existing connections to test_db if any (Postgres specific)
            # This handles the case where previous tests failed to cleanup or other connections exist
            try:
                conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'test_db' AND pid <> pg_backend_pid()"))
            except Exception:
                pass # Might fail if table doesn't exist or permission issues
                
            conn.execute(text("DROP DATABASE IF EXISTS test_db"))
            conn.execute(text("CREATE DATABASE test_db"))
    except Exception as e:
        print(f"Warning during DB setup: {e}")
        # Proceeding might fail if DB doesn't exist, but we return the engine anyway
    finally:
        default_engine.dispose()

    # Connect to Test DB
    engine = create_engine(TEST_DATABASE_URL, poolclass=StaticPool)
    yield engine
    
    # Cleanup
    engine.dispose()
    
    # Drop test DB
    default_engine = create_engine(ORIGINAL_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with default_engine.connect() as conn:
             # Terminate connections again just in case
             try:
                conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'test_db' AND pid <> pg_backend_pid()"))
             except Exception:
                pass
             conn.execute(text("DROP DATABASE IF EXISTS test_db"))
    except Exception as e:
        print(f"Warning during DB teardown: {e}")
    finally:
        default_engine.dispose()

@pytest.fixture(scope="function")
def db_session(db_engine):
    # Create tables
    Base.metadata.create_all(bind=db_engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = SessionLocal()
    
    try:
        yield db
    finally:
        db.close()
        # Drop tables after each test to ensure clean state
        Base.metadata.drop_all(bind=db_engine)
