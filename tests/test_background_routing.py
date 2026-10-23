import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import object_session

from app.main import app
from app.routers import ingredients as ingredients_router
from app.services.recipe_import import service as import_service
from app.services.recipe_import.schemas import RecipeImportDraft


@pytest.fixture
def client(owner_db):
    return TestClient(app)


def test_demo_ingredient_background_tasks_use_demo_db(client, monkeypatch):
    seen = {}

    def record(name, ingredient):
        session = object_session(ingredient)
        seen[name] = (str(session.get_bind().url), ingredient.id, ingredient.name)

    def fake_lookup(ingredient):
        record("nut", ingredient)

    async def fake_link(ingredient, db):
        record("fdc", ingredient)
        return False

    def no_estimator():
        raise ValueError("no AI in tests")

    monkeypatch.setattr(ingredients_router, "_lookup_fdc_macros_sync", fake_lookup)
    monkeypatch.setattr(ingredients_router, "link_ingredient_to_fdc_async", fake_link)
    monkeypatch.setattr(ingredients_router, "get_nutrition_estimator", no_estimator)

    response = client.post(
        "/ingredients/", json={"name": "Demo Thing", "category": "pantry", "base_unit": "g"}
    )

    assert response.status_code == 200, response.text
    created_id = response.json()["id"]
    assert set(seen) == {"fdc", "nut"}
    for url, ing_id, name in seen.values():
        assert url.startswith("sqlite"), seen
        assert (ing_id, name) == (created_id, "Demo Thing")


def test_demo_import_job_uses_demo_db(client, monkeypatch):
    seen = []

    class FakeExtractor:
        async def extract(self, *args, **kwargs):
            return RecipeImportDraft(name="Stub")

    class FakePipeline:
        def __init__(self, db):
            seen.append(str(db.get_bind().url))

        async def run(self, draft, progress_callback):
            return draft

    monkeypatch.setattr(import_service, "ImageExtractor", FakeExtractor)
    monkeypatch.setattr(import_service, "RecipeImportPipeline", FakePipeline)

    response = client.post(
        "/recipes/parse-from-image", files={"file": ("a.png", b"\x89PNG", "image/png")}
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    for _ in range(50):
        job = client.get(f"/recipes/parse-from-image/{job_id}").json()
        if job["status"] in ("completed", "failed", "canceled"):
            break
        time.sleep(0.1)

    assert job["status"] == "completed", job
    assert len(seen) == 1 and seen[0].startswith("sqlite"), seen
