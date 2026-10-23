import pytest
from fastapi.testclient import TestClient

from app.auth import rate_limit
from app.main import app
from app.routers import health


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(rate_limit, "login_limiter", rate_limit.LoginLimiter())


@pytest.fixture
def client(owner_db, monkeypatch):
    async def fake_db():
        return False, "host=secret"

    async def fake_dropbox():
        return False, "token=secret"

    async def fake_google():
        return False, "key=secret"

    monkeypatch.setattr(health, "_check_database", fake_db)
    monkeypatch.setattr(health.dropbox_service, "check_health", fake_dropbox)
    monkeypatch.setattr(health, "_check_google_ai", fake_google)
    return TestClient(app)


def test_extended_anonymous_has_no_details(client):
    response = client.get("/health/extended")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["database"]["status"] == "error"
    assert "details" not in response.text
    assert "secret" not in response.text
    assert "demo" not in body


def test_extended_owner_has_details(client):
    assert client.post("/auth/login", json={"pin": "1234"}).status_code == 200
    response = client.get("/health/extended")
    assert response.status_code == 200
    body = response.json()
    assert body["services"]["database"]["details"] == "host=secret"
    assert body["services"]["dropbox"]["details"] == "token=secret"
    assert body["services"]["google_ai"]["details"] == "key=secret"
    assert set(body["demo"]) == {"last_reset", "current_week_plan"}
