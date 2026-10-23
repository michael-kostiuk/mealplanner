import pytest
from fastapi.testclient import TestClient

from app import models
from app.auth import rate_limit
from app.demo.database import get_demo_session_factory
from app.main import app
from app.services.dropbox_service import dropbox_service


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    monkeypatch.setattr(rate_limit, "login_limiter", rate_limit.LoginLimiter())


@pytest.fixture
def calls(monkeypatch):
    recorded = {"delete": [], "upload": []}

    async def fake_delete(image_url):
        recorded["delete"].append(image_url)
        return True

    async def fake_upload(file_data, filename, folder=None):
        recorded["upload"].append({"filename": filename, "folder": folder})
        return "https://example.com/img.jpg"

    monkeypatch.setattr(dropbox_service, "delete_image", fake_delete)
    monkeypatch.setattr(dropbox_service, "upload_image", fake_upload)
    return recorded


def _recipe_payload(image_url=None):
    return {
        "name": "Updated",
        "servings": 1,
        "prep_time": 1,
        "cook_time": 1,
        "instructions": "x",
        "category": "lunch",
        "calories": 500,
        "protein": 1.0,
        "carbs": 1.0,
        "fats": 1.0,
        "breakfast_weight": 0.5,
        "lunch_weight": 0.5,
        "dinner_weight": 0.5,
        "image_url": image_url,
        "ingredients": [],
    }


@pytest.fixture
def demo_recipe_id(owner_db):
    """Give the first demo recipe an image_url and return its id."""
    session = get_demo_session_factory()()
    try:
        recipe = session.query(models.Recipe).first()
        recipe.image_url = "https://example.com/old.jpg"
        session.commit()
        return recipe.id
    finally:
        session.close()


@pytest.fixture
def owner_recipe_id(owner_db):
    recipe = models.Recipe(
        name="PG Img",
        servings=1,
        prep_time=1,
        cook_time=1,
        instructions="x",
        category="lunch",
        calories=500,
        protein=1.0,
        carbs=1.0,
        fats=1.0,
        image_url="https://example.com/pg.jpg",
    )
    owner_db.add(recipe)
    owner_db.commit()
    return recipe.id


def test_demo_delete_recipe_does_not_delete_image(demo_recipe_id, calls):
    client = TestClient(app)
    assert client.delete(f"/recipes/{demo_recipe_id}").status_code == 200
    assert calls["delete"] == []


def test_demo_update_replacing_image_does_not_delete(demo_recipe_id, calls):
    client = TestClient(app)
    response = client.put(
        f"/recipes/{demo_recipe_id}", json=_recipe_payload("https://example.com/new.jpg")
    )
    assert response.status_code == 200
    assert calls["delete"] == []


def test_demo_upload_goes_to_demo_folder(demo_recipe_id, calls):
    client = TestClient(app)
    response = client.post(
        f"/recipes/{demo_recipe_id}/upload-image",
        files={"file": ("a.jpg", b"abc", "image/jpeg")},
    )
    assert response.status_code == 200
    assert [c["folder"] for c in calls["upload"]] == ["/recipes-demo"]


def test_owner_delete_still_deletes(owner_recipe_id, calls):
    client = TestClient(app)
    assert client.post("/auth/login", json={"pin": "1234"}).status_code == 200
    assert client.delete(f"/recipes/{owner_recipe_id}").status_code == 200
    assert calls["delete"] == ["https://example.com/pg.jpg"]


def test_owner_upload_uses_default_folder(owner_recipe_id, calls):
    client = TestClient(app)
    assert client.post("/auth/login", json={"pin": "1234"}).status_code == 200
    response = client.post(
        f"/recipes/{owner_recipe_id}/upload-image",
        files={"file": ("a.jpg", b"abc", "image/jpeg")},
    )
    assert response.status_code == 200
    assert [c["folder"] for c in calls["upload"]] == [None]
