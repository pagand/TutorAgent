# tests/test_feedback_api.py
import pytest
from fastapi.testclient import TestClient

@pytest.mark.stage1 # Endpoint existed in Stage 1
class TestFeedbackAPI:
    def test_submit_feedback_success(self, client: TestClient):
        """Test submitting feedback returns success (basic check)."""
        response = client.post("/feedback/", json={
            "question_number": 1,
            "hint": "Some hint text",
            "rating": 4,
            "comment": "It was okay."
            # Note: user_id might be needed here depending on final implementation
        })
        assert response.status_code == 200
        assert response.json() == {"status": "Feedback received"} # Check current dummy response

    # TODO @pytest.mark.stage4: Add tests to verify feedback is stored,
    # Requires an endpoint to retrieve logs/feedback or ability to inspect state/DB.
    # For now, we only check if the endpoint accepts the data.
