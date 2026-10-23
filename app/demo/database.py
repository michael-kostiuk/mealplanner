import threading

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from ..config import get_settings

_lock = threading.Lock()
_engine: Engine | None = None
_factory: sessionmaker | None = None


def get_demo_engine() -> Engine:
    global _engine, _factory
    with _lock:
        if _engine is None:
            # Requests are served from a thread pool, so the connection is shared across threads
            _engine = create_engine(
                f"sqlite:///{get_settings().demo_db_path}",
                connect_args={"check_same_thread": False},
            )
            _factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        return _engine


def get_demo_session_factory() -> sessionmaker:
    get_demo_engine()
    assert _factory is not None
    return _factory


def dispose_demo_engine() -> None:
    """Close all connections and forget the engine (next use recreates it)."""
    global _engine, _factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _factory = None
