# tests/test_user_state_api.py
import pytest
from fastapi.testclient import TestClient
from app.utils.config import settings
# Assuming QuestionService is needed to know the correct answer/skill for Q1
from app.services.question_service import question_service

@pytest.mark.stage3
class TestUserStateAPI:
    USER_ID = "state_tester_v2" # Use a different user ID to ensure clean state
    # --- CORRECTED SKILL NAME ---
    SKILL = "[Data Loading]"
    # --- END CORRECTION ---

    # Find a question ID that actually maps to the target SKILL
    # This requires the service to be loaded; might be better in a fixture
    # For simplicity, let's assume Q1 maps to "[Data Loading]"
    QUESTION_ID_FOR_SKILL = 1
    # Assume the correct answer for Q1 is '3'
    CORRECT_ANSWER_FOR_Q1 = "3"
    INCORRECT_ANSWER_FOR_Q1 = "2"


    def test_get_initial_bkt_state(self, client: TestClient):
        """Test retrieving BKT state for a new user."""
        response = client.get(f"/users/{self.USER_ID}/bkt")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Assert using the corrected skill name
        assert self.SKILL in data, f"Expected skill '{self.SKILL}' not found in BKT state keys: {list(data.keys())}"
        # Check initial mastery is default P(L0)
        assert data[self.SKILL] == pytest.approx(settings.bkt_p_l0)

    def test_bkt_state_updates_after_answer(self, client: TestClient):
        """Verify BKT state endpoint reflects changes from /answer."""
        # 1. Get Initial state for the specific skill
        response_before = client.get(f"/users/{self.USER_ID}/bkt")
        assert response_before.status_code == 200
        data_before = response_before.json()
        assert self.SKILL in data_before
        mastery_before = data_before[self.SKILL]
        assert mastery_before == pytest.approx(settings.bkt_p_l0)

        # 2. Submit a correct answer for a question associated with self.SKILL
        answer_payload = {
            "user_id": self.USER_ID,
            "question_number": self.QUESTION_ID_FOR_SKILL,
            "user_answer": self.CORRECT_ANSWER_FOR_Q1, # Use the known correct answer
            "time_taken_ms": 10000
        }
        answer_response = client.post("/answer/", json=answer_payload)
        assert answer_response.status_code == 200
        answer_data = answer_response.json()
        assert answer_data["correct"] is True
        assert answer_data["skill"] == self.SKILL # Verify the question mapped correctly

        # 3. Check BKT state again AFTER the correct answer
        response_after = client.get(f"/users/{self.USER_ID}/bkt")
        assert response_after.status_code == 200
        data_after = response_after.json()
        assert self.SKILL in data_after
        mastery_after = data_after[self.SKILL]

        # Assert that mastery has increased after a correct answer
        assert mastery_after > mastery_before, "Mastery should increase after a correct answer"
        assert mastery_after == pytest.approx(answer_data["current_mastery"]) # Check consistency with /answer response

    def test_get_full_user_state_after_incorrect_answer(self, client: TestClient):
        """
        Test retrieving the full user state after submitting one incorrect answer.
        Verifies log content and consecutive error count.
        """
        # 1. Submit an incorrect answer to populate state
        answer_payload = {
            "user_id": self.USER_ID,
            "question_number": self.QUESTION_ID_FOR_SKILL, # Use the same question
            "user_answer": self.INCORRECT_ANSWER_FOR_Q1, # Use a known incorrect answer
            "time_taken_ms": 12000 # Add time_taken_ms if required by AnswerRequest model
        }
        answer_response = client.post("/answer/", json=answer_payload)
        assert answer_response.status_code == 200
        answer_data = answer_response.json()
        assert answer_data["correct"] is False
        assert answer_data["skill"] == self.SKILL

        # 2. Retrieve the full user state
        response = client.get(f"/users/{self.USER_ID}/state")
        assert response.status_code == 200
        data = response.json()

        # 3. Validate the structure and content
        assert "bkt" in data
        assert "log" in data
        assert "consecutive_errors" in data

        # Check BKT state reflects the incorrect answer (mastery likely decreased)
        assert self.SKILL in data["bkt"]
        assert data["bkt"][self.SKILL] < settings.bkt_p_l0 # Should be lower than initial

        # Check log content (assuming state is clean for this user before this test)
        # Note: If other tests ran before for the same user, log length might be > 1
        # It's better to check the content of the *last* log entry
        assert isinstance(data["log"], list)
        assert len(data["log"]) >= 1 # Should have at least the entry from this test
        last_log_entry = data["log"][-1] # Get the most recent log
        assert last_log_entry["action"] == "answered"
        assert last_log_entry["question_id"] == self.QUESTION_ID_FOR_SKILL
        assert last_log_entry["skill"] == self.SKILL
        assert last_log_entry["user_answer"] == self.INCORRECT_ANSWER_FOR_Q1
        assert last_log_entry["is_correct"] is False
        assert last_log_entry["time_taken_ms"] == 12000

        # Check consecutive errors for the specific skill
        assert self.SKILL in data["consecutive_errors"]
        # Assuming this is the first interaction for this skill in this test scope
        assert data["consecutive_errors"][self.SKILL] == 1, "Consecutive errors should be 1 after one incorrect answer"

    # TODO @pytest.mark.stage4: Add tests for getting/setting user preferences via this API if added