# tests/test_stage_4_5_enums.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.enums import HintStyle

client = TestClient(app)

@pytest.mark.stage4_5
def test_update_preferences_with_valid_enum():
    """
    Tests that the preferences endpoint correctly accepts and validates
    a valid member of the HintStyle enum.
    """
    user_id = "enum_test_user"
    # Use the enum member's value for the request
    style = HintStyle.SOCRATIC_QUESTION.value
    
    response = client.put(
        f"/users/{user_id}/preferences",
        json={"preferred_hint_style": style, "feedback_preference": "on_demand"}
    )
    assert response.status_code == 200
    assert response.json()["preferred_hint_style"] == style

@pytest.mark.stage4_5
def test_update_preferences_with_invalid_enum():
    """
    Tests that the preferences endpoint returns a 422 Unprocessable Entity
    error when an invalid string is provided for the hint style.
    """
    user_id = "enum_test_user_invalid"
    invalid_style = "Invalid Style"
    
    response = client.put(
        f"/users/{user_id}/preferences",
        json={"preferred_hint_style": invalid_style, "feedback_preference": "on_demand"}
    )
    assert response.status_code == 422
