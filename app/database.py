from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import sessionmaker

from .auth.deps import AuthContext, get_auth
from .db_core import DATABASE_URL, SessionLocal, engine, get_owner_session_factory
from .demo.database import get_demo_session_factory

__all__ = [
    "DATABASE_URL",
    "SessionLocal",
    "engine",
    "get_db",
    "get_owner_session_factory",
    "get_session_factory",
]


def get_session_factory(
    auth: Annotated[AuthContext, Depends(get_auth)],
    owner_factory: Annotated[sessionmaker, Depends(get_owner_session_factory)],
) -> sessionmaker:
    """Owner requests use Postgres, everyone else the SQLite demo DB."""
    if auth.mode == "owner":
        return owner_factory
    # Lazy: demo.lifecycle imports routers, which import get_db from this module
    from .demo.lifecycle import ensure_demo_fresh

    ensure_demo_fresh()
    return get_demo_session_factory()


def get_db(factory: Annotated[sessionmaker, Depends(get_session_factory)]):
    db = factory()
    try:
        yield db
    finally:
        db.close()
