# tests/test_session.py
# Tests for exam session timer endpoints.
import time
import pytest


async def test_session_start_creates_session(client):
    """POST /session/start should create a session and return start time."""
    await client.post("/users/", json={"user_id": "timer_user_01"})
    response = await client.post("/session/start", json={
        "user_id": "timer_user_01",
        "session_id": "uuid-abc-123"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "timer_user_01"
    assert data["session_id"] == "uuid-abc-123"
    assert data["exam_start_ms"] > 0
    assert data["exam_duration_ms"] == 25 * 60 * 1000
    assert data["ms_remaining"] > 0
    assert data["ms_remaining"] <= 25 * 60 * 1000


async def test_session_start_idempotent(client):
    """Calling /session/start twice must return the SAME start time (page reload safety)."""
    await client.post("/users/", json={"user_id": "timer_user_02"})

    r1 = await client.post("/session/start", json={
        "user_id": "timer_user_02",
        "session_id": "uuid-first"
    })
    r2 = await client.post("/session/start", json={
        "user_id": "timer_user_02",
        "session_id": "uuid-second"  # different UUID, should be ignored
    })

    assert r1.json()["exam_start_ms"] == r2.json()["exam_start_ms"]
    # session_id must stay the original one
    assert r2.json()["session_id"] == "uuid-first"


async def test_session_remaining_returns_correct_time(client):
    """GET /session/{user_id}/remaining should return remaining time."""
    await client.post("/users/", json={"user_id": "timer_user_03"})
    await client.post("/session/start", json={
        "user_id": "timer_user_03",
        "session_id": "uuid-remaining"
    })

    response = await client.get("/session/timer_user_03/remaining")
    assert response.status_code == 200
    data = response.json()
    assert data["ms_remaining"] > 0
    assert data["expired"] is False


async def test_session_remaining_404_if_no_session(client):
    """GET /session/remaining without a started session should return 404."""
    await client.post("/users/", json={"user_id": "timer_user_no_session"})
    response = await client.get("/session/timer_user_no_session/remaining")
    assert response.status_code == 404


async def test_session_start_unknown_user_returns_404(client):
    response = await client.post("/session/start", json={
        "user_id": "ghost_user",
        "session_id": "uuid-xyz"
    })
    assert response.status_code == 404
