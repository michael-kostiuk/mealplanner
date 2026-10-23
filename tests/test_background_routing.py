import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import ingredients as ingredients_router
from app.services.recipe_import import service as import_service
from app.services.recipe_import.schemas import RecipeImportDraft


@pytest.fixture
def client(owner_db):
    return TestClient(app)


def test_demo_ingredient_background_tasks_use_demo_db(client, monkeypatch):
    seen = {}

    def record(name):
        def fake_sync(ingredient_id, session_factory):
            with session_factory() as db:
                seen[name] = str(db.get_bind().url)

        return fake_sync

    monkeypatch.setattr(ingredients_router, "_link_fdc_background_sync", record("fdc"))
    monkeypatch.setattr(ingredients_router, "_estimate_nutrition_background_sync", record("nut"))

    response = client.post(
        "/ingredients/", json={"name": "Demo Thing", "category": "pantry", "base_unit": "g"}
    )

    assert response.status_code == 200, response.text
    assert set(seen) == {"fdc", "nut"}
    assert all(url.startswith("sqlite") for url in seen.values()), seen


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
