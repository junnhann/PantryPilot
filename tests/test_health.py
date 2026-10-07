from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "gemini_api_key" not in r.json()  # never leak secrets


def test_recipe_routes_demo(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "DEMO_MODE", True)
    c = TestClient(app)
    opts = c.post("/api/recipes", json={"goal": "chocolate cake", "servings": 6}).json()["options"]
    r = c.post("/api/ingredients", json={"goal": "cake", "recipe_title": opts[0]["title"], "servings": 6})
    assert r.status_code == 200 and r.json()["ingredients"]
    # validation: servings 0 rejected
    assert c.post("/api/recipes", json={"goal": "cake", "servings": 0}).status_code == 422
