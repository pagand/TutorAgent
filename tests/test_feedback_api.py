# tests/test_feedback_api.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_submit_feedback():
    response = client.post("/feedback/", json={
        "user_id": "testuser",
        "question_id": 1,
        "hint_style": "test_style",
        "rating": 5,
        "comment": "Great hint!"
    })
    assert response.status_code == 200
    assert response.json() == {"message": "Feedback received and recorded"}