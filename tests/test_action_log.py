# tests/test_action_log.py
# Tests for the fine-grained user action logging and intervention logging endpoints.
import pytest


async def _create_user(client, user_id: str):
    await client.post("/users/", json={"user_id": user_id})


async def test_log_question_view(client):
    await _create_user(client, "log_user_01")
    response = await client.post("/log/action", json={
        "user_id": "log_user_01",
        "session_id": "sess-1",
        "action_type": "question_view",
        "question_number": 3,
        "action_data": {"from_question": 2}
    })
    assert response.status_code == 200
    assert response.json()["logged"] is True


async def test_log_choice_select(client):
    await _create_user(client, "log_user_02")
    response = await client.post("/log/action", json={
        "user_id": "log_user_02",
        "session_id": "sess-2",
        "action_type": "choice_select",
        "question_number": 1,
        "action_data": {"choice_index": 2, "choice_text": "Network Layer"}
    })
    assert response.status_code == 200


async def test_log_answer_submit(client):
    await _create_user(client, "log_user_03")
    response = await client.post("/log/action", json={
        "user_id": "log_user_03",
        "session_id": "sess-3",
        "action_type": "answer_submit",
        "question_number": 1,
        "action_data": {
            "answer": "Network",
            "is_correct": True,
            "attempt_number": 1,
            "time_on_question_ms": 32000
        }
    })
    assert response.status_code == 200


async def test_log_hint_feedback(client):
    await _create_user(client, "log_user_04")
    response = await client.post("/log/action", json={
        "user_id": "log_user_04",
        "session_id": "sess-4",
        "action_type": "hint_feedback",
        "question_number": 2,
        "action_data": {"rating": 4, "hint_style": "Socratic Question"}
    })
    assert response.status_code == 200


async def test_log_unknown_action_type_still_accepted(client):
    """Unknown action types should not be rejected — log with warning."""
    await _create_user(client, "log_user_05")
    response = await client.post("/log/action", json={
        "user_id": "log_user_05",
        "session_id": "sess-5",
        "action_type": "some_future_action",
        "action_data": {}
    })
    assert response.status_code == 200


async def test_log_intervention_offered(client):
    await _create_user(client, "intv_user_01")
    response = await client.post("/log/intervention", json={
        "user_id": "intv_user_01",
        "session_id": "sess-int-1",
        "question_number": 4,
        "time_on_question_ms": 75000,
        "mastery_at_trigger": 0.3,
        "accepted": None
    })
    assert response.status_code == 200
    assert response.json()["logged"] is True


async def test_log_intervention_accepted(client):
    await _create_user(client, "intv_user_02")
    # First: log the offer
    await client.post("/log/intervention", json={
        "user_id": "intv_user_02",
        "session_id": "sess-int-2",
        "question_number": 5,
        "time_on_question_ms": 80000,
        "mastery_at_trigger": 0.2,
        "accepted": None
    })
    # Then: log the acceptance (should update existing row)
    response = await client.post("/log/intervention", json={
        "user_id": "intv_user_02",
        "session_id": "sess-int-2",
        "question_number": 5,
        "time_on_question_ms": 82000,
        "mastery_at_trigger": 0.2,
        "accepted": True
    })
    assert response.status_code == 200


async def test_log_intervention_rejected(client):
    await _create_user(client, "intv_user_03")
    await client.post("/log/intervention", json={
        "user_id": "intv_user_03",
        "session_id": "sess-int-3",
        "question_number": 7,
        "time_on_question_ms": 90000,
        "accepted": None
    })
    response = await client.post("/log/intervention", json={
        "user_id": "intv_user_03",
        "session_id": "sess-int-3",
        "question_number": 7,
        "time_on_question_ms": 91000,
        "accepted": False
    })
    assert response.status_code == 200


async def test_log_session_start_and_complete(client):
    await _create_user(client, "log_user_session")
    for action in ("session_start", "session_complete"):
        r = await client.post("/log/action", json={
            "user_id": "log_user_session",
            "session_id": "sess-sc",
            "action_type": action,
            "action_data": {"question_count": 22}
        })
        assert r.status_code == 200
