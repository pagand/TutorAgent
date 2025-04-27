# tests/test_hints_api.py
import pytest
import os
from fastapi.testclient import TestClient

# This fixture ensures ChromaDB is set up before these tests run
@pytest.mark.usefixtures("setup_test_chromadb")
class TestHintsAPI:

    # Uses the default mock LLM from conftest.py
    # @pytest.mark.stage2
    # def test_get_hint_success_mocked(self, client: TestClient):
    #     """Test getting a hint with mocked LLM (Stage 2+)."""
    #     response = client.post("/hints/", json={
    #         "user_id": "test_user_hints",
    #         "question_number": 1,
    #         "user_answer": "Some answer"
    #     })
    #     assert response.status_code == 200
    #     data = response.json()
    #     assert data["question_number"] == 1
    #     assert data["hint"] == "This is a mocked hint from the test fixture." # Check mock response

    # Example of testing with a real LLM (requires setup and API key)
    @pytest.mark.stage5 # Test added/relevant in Stage 5
    @pytest.mark.llm_integration # Custom marker to run only when desired
    @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY") and not os.getenv("LLM_PROVIDER", "").lower() == "ollama",
                        reason="Requires OPENAI_API_KEY or Ollama running/configured")
    def test_get_hint_real_llm(self, client: TestClient):
        """Test getting a hint hitting a real LLM (requires API key/Ollama)."""
        # Temporarily override settings if needed for this specific test
        # Or ensure .env is configured correctly before running
        print("not .............")

        response = client.post("/hints/", json={
            "user_id": "test_user_real_llm",
            "question_number": 1,
            "user_answer": "An incorrect answer"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["question_number"] == 1
        assert isinstance(data["hint"], str)
        assert len(data["hint"]) > 10 # Check for a plausible hint length
        assert "mocked" not in data["hint"] # Ensure it's not the mocked response

    @pytest.mark.stage2
    def test_get_hint_question_not_found(self, client: TestClient):
        """Test hint request for non-existent question."""
        response = client.post("/hints/", json={
            "user_id": "test_user_hints_404", "question_number": 9999
        })
        assert response.status_code == 404

    @pytest.mark.stage1
    def test_get_hint_method_not_allowed(self, client: TestClient):
        """Test wrong HTTP method for hints."""
        response = client.get("/hints/")
        assert response.status_code == 405

    # TODO @pytest.mark.stage4: Add tests for hints based on personalization preferences
