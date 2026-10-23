import contextlib
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test env for app.config; assigned (not setdefault) so a real .env never leaks into tests.
# Must happen before importing anything from `app`.
from argon2 import PasswordHasher  # noqa: E402

os.environ["SESSION_SECRET"] = "test-secret-not-for-prod"
os.environ["OWNER_PIN_HASH"] = PasswordHasher().hash("1234")
os.environ["OWNER_USER_ID"] = "1"
os.environ["COOKIE_SECURE"] = "false"
os.environ["DEMO_DB_PATH"] = os.path.join(tempfile.gettempdir(), "mealplanner_test_demo.sqlite")
os.environ["DEMO_SEED_PATH"] = "tests/fixtures/demo_seed_small.json"

from app.models import Base  # noqa: E402

# Use a test database URL.
# We will assume we can create a database named 'test_db' on the same host.
# The original URL is likely postgresql://postgres:postgres@dbmp:5432/postgres
# We want postgresql://postgres:postgres@dbmp:5432/test_db

ORIGINAL_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@dbmp:5432/postgres"
)
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
            with contextlib.suppress(Exception):
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'test_db' AND pid <> pg_backend_pid()"
                    )
                )

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
            with contextlib.suppress(Exception):
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'test_db' AND pid <> pg_backend_pid()"
                    )
                )
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


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    """A freshly built demo DB in tmp_path (seed: tests/fixtures/demo_seed_small.json)."""
    from app.config import get_settings
    from app.demo import database as demo_database
    from app.demo.lifecycle import rebuild_demo_db

    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "demo.sqlite"))
    get_settings.cache_clear()
    demo_database.dispose_demo_engine()
    rebuild_demo_db()
    yield
    demo_database.dispose_demo_engine()
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def owner_db(db_engine, db_session, demo_db):
    """Point the owner path at test_db (user id 1 exists) and the demo path at a tmp demo DB."""
    from app.auth.deps import reset_user_cache
    from app.db_core import get_owner_session_factory
    from app.main import app
    from app.models import User

    db_session.add(User(id=1, email="owner@example.com"))
    db_session.commit()
    reset_user_cache()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    app.dependency_overrides[get_owner_session_factory] = lambda: factory
    yield db_session
    app.dependency_overrides.pop(get_owner_session_factory, None)
    reset_user_cache()
