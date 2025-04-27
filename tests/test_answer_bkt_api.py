# tests/test_answer_bkt_api.py
import pytest
from fastapi.testclient import TestClient
from app.utils.config import settings # Import settings for default P(L0)

@pytest.mark.stage3
# @pytest.mark.usefixtures("setup_test_chromadb") # Keep if needed for other tests/setup
class TestAnswerBKTFlow:
    USER_ID = "bkt_tester"
    # --- CORRECTED SKILL NAME ---
    SKILL = "[Data Loading]"
    # --- END CORRECTION ---

    def test_initial_bkt_state(self, client: TestClient):
       """Test retrieving BKT state for a new user via the dedicated endpoint."""
       response = client.get(f"/users/{self.USER_ID}/bkt")
       assert response.status_code == 200
       data = response.json()
       # Assert using the corrected skill name
       assert self.SKILL in data, f"Expected skill '{self.SKILL}' not found in BKT state keys: {list(data.keys())}"
       # Check default P(L0) from settings
       assert data[self.SKILL] == pytest.approx(settings.bkt_p_l0)


    def test_answer_sequence_and_intervention(self, client: TestClient):
        """
        Simulate a sequence of answers and verify correctness feedback,
        intervention triggers, and implicit BKT updates affecting intervention.
        Assumes questions 1-4 exist and map to skills appropriately for the test logic.
        NOTE: This test relies on specific question details (ID, skill, correct answer)
              and intervention rules (mastery < 0.4, errors >= 2, time > 60s).
        """
        # Ensure initial state for the specific skill is default
        initial_response = client.get(f"/users/{self.USER_ID}/bkt")
        assert initial_response.status_code == 200
        assert initial_response.json()[self.SKILL] == pytest.approx(settings.bkt_p_l0)

        # Interaction 1: Q1 Incorrect (Assume Q1 maps to self.SKILL or similar)
        # Need to know the correct answer for Q1 to ensure user_answer '2' is incorrect.
        # Let's assume correct answer for Q1 is '1' and it maps to self.SKILL
        response1 = client.post("/answer/", json={
            "user_id": self.USER_ID, "question_number": 1, "user_answer": "2", "time_taken_ms": 10000
        })
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["correct"] is False
        # Check intervention based on initial low mastery (assuming threshold is > default 0.2)
        assert data1["intervention_needed"] is True, f"Intervention should be needed due to low initial mastery ({data1['current_mastery']})"
        # Verify mastery decreased (or stayed low)
        assert data1["current_mastery"] < settings.bkt_p_l0

        # Interaction 2: Q2 Incorrect (Assume Q2 also maps to self.SKILL for error tracking)
        # Assume correct answer for Q2 is '1'
        response2 = client.post("/answer/", json={
            "user_id": self.USER_ID, "question_number": 2, "user_answer": "2", "time_taken_ms": 15000
        })
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["correct"] is False
        # Check intervention based on consecutive errors (should now be 2 for self.SKILL)
        assert data2["intervention_needed"] is True, "Intervention should be needed due to >= 2 consecutive errors"
        assert data2["current_mastery"] < data1["current_mastery"] # Mastery likely decreased further


        # Interaction 3: Q3 Correct (Assume Q3 maps to self.SKILL)
        # Assume correct answer for Q3 is '4'
        response3 = client.post("/answer/", json={
            "user_id": self.USER_ID, "question_number": 3, "user_answer": "4", "time_taken_ms": 20000
        })
        assert response3.status_code == 200
        data3 = response3.json()
        assert data3["correct"] is True
        # Check intervention reset (errors reset, mastery might still be low but errors rule doesn't apply)
        assert data3["intervention_needed"] is False, "Intervention should be False after a correct answer resets errors"
        assert data3["current_mastery"] > data2["current_mastery"] # Mastery increased

        # Interaction 4: Q4 Correct but Slow (Assume Q4 maps to self.SKILL)
        # Assume correct answer for Q4 is '4'
        response4 = client.post("/answer/", json={
            "user_id": self.USER_ID, "question_number": 4, "user_answer": "4", "time_taken_ms": 70000 # Exceeds 60s threshold
        })
        assert response4.status_code == 200
        data4 = response4.json()
        assert data4["correct"] is True
         # Check intervention based on time limit (assuming settings.intervention_time_threshold_ms = 60000)
        assert data4["intervention_needed"] is True, "Intervention should be needed due to exceeding time threshold"
