"""FastAPI auth dependencies (owner vs demo routing). Rationale: see app/auth/__init__.py."""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy.orm import sessionmaker

from app import models
from app.auth.session import SESSION_COOKIE, decode_session
from app.db_core import get_owner_session_factory

DEMO_USER_ID = 1

# Owner ids confirmed to exist in Postgres. Only hits are cached, so a user created later is
# picked up on the next request. Reset in tests with reset_user_cache().
_known_users: set[int] = set()


def reset_user_cache() -> None:
    _known_users.clear()


@dataclass(frozen=True)
class AuthContext:
    mode: Literal["owner", "demo"]
    user_id: int


def _owner_exists(user_id: int, owner_factory: sessionmaker) -> bool:
    if user_id in _known_users:
        return True
    with owner_factory() as db:
        found = db.get(models.User, user_id) is not None
    if found:
        _known_users.add(user_id)
    return found


def get_auth(
    request: Request,
    owner_factory: Annotated[sessionmaker, Depends(get_owner_session_factory)],
) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = decode_session(token) if token else None
    # A validly signed cookie for a user missing from Postgres is treated as anonymous
    if user_id is None or not _owner_exists(user_id, owner_factory):
        return AuthContext("demo", DEMO_USER_ID)
    return AuthContext("owner", user_id)
