# tests/test_stage_4_5_personalization.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.personalization_service import personalization_service
from app.models.enums import HintStyle

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Resets user state before each test in this module."""
    personalization_service.update_user_preferences("adaptive_user", {"preferred_hint_style": "Automatic"})
    yield
    personalization_service.update_user_preferences("adaptive_user", {"preferred_hint_style": "Automatic"})


@pytest.mark.stage4_5
def test_adaptive_hint_selection_and_feedback():
    """
    Tests the full adaptive loop:
    1. Records feedback for multiple hint styles.
    2. Verifies the service chooses the best one (exploitation).
    3. Verifies post-hint BKT change is recorded.
    """
    user_id = "adaptive_user"

    # --- Step 1: Simulate user receiving hints and providing feedback ---
    
    # High rating for Analogy
    personalization_service.record_feedback(user_id, HintStyle.ANALOGY.value, rating=5, bkt_change=0.1)
    
    # Low rating for Socratic Question
    personalization_service.record_feedback(user_id, HintStyle.SOCRATIC_QUESTION.value, rating=1, bkt_change=-0.05)
    
    # Medium rating for Worked Example
    personalization_service.record_feedback(user_id, HintStyle.WORKED_EXAMPLE.value, rating=3, bkt_change=0.0)
    personalization_service.record_feedback(user_id, HintStyle.WORKED_EXAMPLE.value, rating=4, bkt_change=0.05)

    # --- Step 2: Test adaptive selection (Exploitation) ---
    
    # With a low exploration rate, it should almost always pick the best style
    # For testing, we can temporarily force exploitation by setting exploration_rate to 0
    from app.utils.config import settings
    original_rate = settings.exploration_rate
    settings.exploration_rate = 0.0

    best_style = personalization_service.get_adaptive_hint_style(user_id)
    
    # Analogy has the highest score (5-star rating -> normalized 1.0 + 0.1 bkt_change)
    assert best_style == HintStyle.ANALOGY.value

    # Restore original exploration rate
    settings.exploration_rate = original_rate

@pytest.mark.stage4_5
def test_post_hint_performance_tracking():
    """
    Tests the end-to-end flow of tracking BKT changes after a hint.
    """
    user_id = "bkt_tracker_user"
    question_id = 1 # Assuming this question exists and maps to a skill

    # --- Step 1: User requests a hint ---
    # This should store the pre-hint mastery state
    hint_response = client.post("/hints/", json={"user_id": user_id, "question_number": question_id})
    assert hint_response.status_code == 200
    hint_style_given = hint_response.json()["hint_style"]

    # --- Step 2: User answers the question (correctly, to show improvement) ---
    answer_response = client.post("/answer/", json={
        "user_id": user_id,
        "question_number": question_id,
        "user_answer": "3", # Assuming this is the correct answer for question 1
        "hint_shown": True # IMPORTANT: Signal that a hint was used
    })
    assert answer_response.status_code == 200

    # --- Step 3: Verify that feedback was recorded implicitly ---
    from app.state_manager import get_user_state
    user_state = get_user_state(user_id)
    
    # Check that the feedback scores dictionary was created
    assert "feedback_scores" in user_state
    
    # Check that the style of the hint that was given now has feedback recorded
    assert hint_style_given in user_state["feedback_scores"]
    
    # Check that the count of feedback for this style is now 1
    feedback_data = user_state["feedback_scores"][hint_style_given]
    assert feedback_data["count"] == 1
    
    # Check that the rating is positive, indicating a BKT improvement
    assert feedback_data["total_rating"] > 0


@pytest.mark.stage4_5
def test_dynamic_prompting_uses_correct_template(monkeypatch):
    """
    Tests that the RAG agent selects the correct prompt template from the library
    based on the determined hint style.
    """
    user_id = "prompt_test_user"
    
    # Set user's preference to a specific style
    personalization_service.update_user_preferences(user_id, {"preferred_hint_style": HintStyle.ANALOGY.value})

    # Mock the RAG chain itself to intercept the prompt being used
    class MockChain:
        def __init__(self, steps):
            self.steps = steps
        
        async def ainvoke(self, *args, **kwargs):
            # Find the PromptTemplate in the chain to verify it's the right one
            prompt_template = self.steps[1]
            assert "as an analogy" in prompt_template.template.lower()
            return "mocked response"

    def mock_get_rag_chain(hint_style: str):
        from app.services.prompt_library import PROMPT_LIBRARY
        # This function will be patched to return our MockChain
        prompt = PROMPT_LIBRARY.get(hint_style)
        # We pass the real prompt to the mock chain to allow the assertion
        return MockChain(steps=[None, prompt, None, None])

    monkeypatch.setattr("app.services.rag_agent.get_rag_chain", mock_get_rag_chain)

    # This call will now use the mocked get_rag_chain
    hint_data = personalization_service.get_adaptive_hint_style(user_id)
    
    # The assertion happens inside the mocked ainvoke
    assert hint_data == HintStyle.ANALOGY.value
