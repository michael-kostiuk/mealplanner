import pytest

from app.config import load_settings


def test_missing_required_vars_raise(monkeypatch):
    for name in ("SESSION_SECRET", "OWNER_PIN_HASH", "OWNER_USER_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    for name in ("SESSION_SECRET", "OWNER_PIN_HASH", "OWNER_USER_ID"):
        assert name in str(exc.value)


def test_cors_origins_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://mplanner.online, http://localhost:5173")
    assert load_settings().cors_origins == ["https://mplanner.online", "http://localhost:5173"]


def test_cookie_secure_false(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    assert load_settings().cookie_secure is False
