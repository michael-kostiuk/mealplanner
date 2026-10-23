"""Signed session cookie. Rationale: see app/auth/__init__.py."""

from itsdangerous import BadData, URLSafeTimedSerializer

from app.config import get_settings

SESSION_COOKIE = "mp_session"
SESSION_MAX_AGE = 180 * 24 * 3600


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="mp-session")


def encode_session(user_id: int) -> str:
    return _serializer().dumps(user_id)


def decode_session(token: str) -> int | None:
    try:
        user_id = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadData:
        return None
    return user_id if isinstance(user_id, int) else None
