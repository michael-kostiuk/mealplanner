import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import rate_limit
from app.auth.session import SESSION_COOKIE, encode_session
from app.main import app


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(rate_limit, "login_limiter", rate_limit.LoginLimiter())


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, pin):
    return client.post("/auth/login", json={"pin": pin})


def test_me_without_cookie_is_demo(client):
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json() == {"mode": "demo", "login_locked_for": 0}


def test_login_correct_pin_sets_cookie(client, owner_db):
    response = _login(client, "1234")
    assert response.status_code == 200
    assert response.json() == {"mode": "owner", "login_locked_for": 0}
    assert SESSION_COOKIE in response.cookies

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Max-Age=15552000" in set_cookie
    assert "Path=/" in set_cookie
    assert "domain" not in set_cookie.lower()

    assert client.get("/auth/me").json()["mode"] == "owner"


def test_wrong_pin_401_then_429_after_three(client):
    assert [_login(client, "0000").status_code for _ in range(3)] == [401, 401, 401]

    response = _login(client, "1234")
    assert response.status_code == 429
    assert response.json()["retry_after"] == 3600
    assert response.headers["retry-after"] == "3600"
    assert client.get("/auth/me").json()["login_locked_for"] == 3600


def test_malformed_pin_422_not_counted(client):
    assert _login(client, "12a4").status_code == 422
    assert [_login(client, "0000").status_code for _ in range(3)] == [401, 401, 401]


def test_tampered_cookie_is_demo(client):
    token = encode_session(1)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    client.cookies.set(SESSION_COOKIE, tampered)

    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"


def test_logout_clears_cookie(client, owner_db):
    _login(client, "1234")
    assert client.get("/auth/me").json()["mode"] == "owner"

    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"
    assert client.get("/auth/me").json()["mode"] == "demo"


@pytest.mark.asyncio
async def test_parallel_wrong_pins_cannot_exceed_limit():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = await asyncio.gather(
            *[ac.post("/auth/login", json={"pin": "0000"}) for _ in range(10)]
        )
    codes = sorted(r.status_code for r in responses)
    assert codes == [401] * 3 + [429] * 7
