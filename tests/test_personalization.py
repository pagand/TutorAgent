# tests/test_personalization.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_default_preferences():
    response = client.get("/users/testuser/preferences")
    assert response.status_code == 200
    preferences = response.json()
    assert preferences["preferred_hint_style"] == "Worked Example"
    assert preferences["feedback_preference"] == "immediate"

def test_update_preferences():
    response = client.put("/users/testuser/preferences", json={"preferred_hint_style": "Socratic", "feedback_preference": "on_demand"})
    assert response.status_code == 200
    assert response.json()["preferred_hint_style"] == "Socratic"

    response = client.get("/users/testuser/preferences")
    assert response.status_code == 200
    assert response.json()["preferred_hint_style"] == "Socratic"
