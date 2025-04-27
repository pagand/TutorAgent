# tests/test_questions_api.py
import pytest
from fastapi.testclient import TestClient

@pytest.mark.stage1 # Feature existed from Stage 1
class TestQuestionsAPI:
    def test_get_all_questions(self, client: TestClient):
        """Test retrieving all questions."""
        response = client.get("/questions/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0 # Assumes test questions.csv has data
        assert "question_number" in data[0]
        assert "question" in data[0]
        assert "skill" in data[0]

    def test_get_specific_question_success(self, client: TestClient):
        """Test retrieving a known existing question."""
        response = client.get("/questions/1")
        assert response.status_code == 200
        data = response.json()
        assert data["question_number"] == 1

    def test_get_specific_question_not_found(self, client: TestClient):
        """Test retrieving a non-existent question."""
        response = client.get("/questions/9999")
        assert response.status_code == 404