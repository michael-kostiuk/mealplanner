from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app


def _monday() -> datetime:
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


def test_demo_regenerates_current_week_plan_after_delete(demo_db):
    client = TestClient(app)
    plans = client.get("/meal-plans/").json()
    current = [p for p in plans if p["start_date"].startswith(_monday().date().isoformat())]
    assert len(current) == 1

    assert client.delete(f"/meal-plans/{current[0]['id']}").status_code == 200

    plans = client.get("/meal-plans/").json()
    assert any(p["start_date"].startswith(_monday().date().isoformat()) for p in plans)
