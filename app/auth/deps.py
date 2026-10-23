"""FastAPI auth dependencies (owner vs demo routing). Rationale: see app/auth/__init__.py."""

from dataclasses import dataclass
from typing import Literal

from fastapi import Request

from app.auth.session import SESSION_COOKIE, decode_session

DEMO_USER_ID = 1


@dataclass(frozen=True)
class AuthContext:
    mode: Literal["owner", "demo"]
    user_id: int


def get_auth(request: Request) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = decode_session(token) if token else None
    if user_id is None:
        return AuthContext("demo", DEMO_USER_ID)
    return AuthContext("owner", user_id)
