import threading
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from ..config import get_settings

_SUFFIXES = ("", "-wal", "-shm", "-journal")


@dataclass(frozen=True)
class Generation:
    """One demo DB file with its engine. Rebuilds create a new generation instead of
    recreating the file in place, so in-flight connections never see their file swapped."""

    path: Path
    engine: Engine
    factory: sessionmaker


_lock = threading.Lock()
_current: Generation | None = None
_previous: Generation | None = None


def _generation_glob() -> tuple[Path, str]:
    base = Path(get_settings().demo_db_path)
    return base.parent, f"{base.stem}-*{base.suffix}*"


def _retire(gen: Generation | None) -> None:
    if gen is None:
        return
    gen.engine.dispose()
    for suffix in _SUFFIXES:
        Path(str(gen.path) + suffix).unlink(missing_ok=True)


def cleanup_leftover_files() -> None:
    """Remove generation files left behind by earlier runs."""
    directory, pattern = _generation_glob()
    for leftover in directory.glob(pattern):
        leftover.unlink(missing_ok=True)


def new_generation() -> Generation:
    """Create an engine for a fresh, not yet populated DB file next to the configured path."""
    base = Path(get_settings().demo_db_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    path = base.with_name(f"{base.stem}-{time.time_ns()}{base.suffix}")
    # Requests are served from a thread pool, so connections are shared across threads
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_foreign_keys)
    return Generation(path, engine, sessionmaker(autocommit=False, autoflush=False, bind=engine))


def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite ignores foreign keys unless asked per connection. The models rely on
    ON DELETE CASCADE (passive_deletes), so without this deleting a shopping list
    leaves its items behind and a reused id picks them up."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def install_generation(gen: Generation) -> None:
    """Atomically make `gen` current; keep one previous generation for in-flight sessions."""
    global _current, _previous
    with _lock:
        stale = _previous
        _previous, _current = _current, gen
    _retire(stale)


def has_generation() -> bool:
    with _lock:
        return _current is not None


def get_demo_session_factory() -> sessionmaker:
    with _lock:
        if _current is None:
            raise RuntimeError("Demo database has not been built yet")
        return _current.factory


def get_demo_engine() -> Engine:
    with _lock:
        if _current is None:
            raise RuntimeError("Demo database has not been built yet")
        return _current.engine


def dispose_demo_engine() -> None:
    """Drop every generation (engines and files)."""
    global _current, _previous
    with _lock:
        gens, _current, _previous = (_current, _previous), None, None
    for gen in gens:
        _retire(gen)
