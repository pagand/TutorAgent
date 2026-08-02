# tests/test_session.py
# Tests for exam session timer endpoints.
import time
import pytest
from sqlalchemy import text
from app.utils.config import settings


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
    assert data["exam_duration_ms"] == settings.exam_duration_ms
    assert data["ms_remaining"] > 0
    assert data["ms_remaining"] <= settings.exam_duration_ms


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


async def test_session_expired_after_duration_reduced(client, db_session):
    """Reducing exam_duration_ms below elapsed time marks the session expired.

    This covers the admin 'Adjust Timer' with a negative value — e.g. subtracting
    minutes when a student needs to be timed out early.
    """
    await client.post("/users/", json={"user_id": "timer_reduce_01"})
    await client.post("/session/start", json={
        "user_id": "timer_reduce_01",
        "session_id": "uuid-reduce"
    })

    # Simulate the admin subtracting enough time to make the session already expired:
    # set exam_duration_ms to 1 ms so elapsed >> duration.
    await db_session.execute(
        text("UPDATE exam_sessions SET exam_duration_ms=1 WHERE user_id='timer_reduce_01'")
    )
    await db_session.commit()

    response = await client.get("/session/timer_reduce_01/remaining")
    assert response.status_code == 200
    data = response.json()
    assert data["ms_remaining"] == 0
    assert data["expired"] is True


async def test_session_submit_blocks_login_as_completed(client, db_session):
    """After /session/submit, participant state must be 'completed' so login gate rejects them.

    This is the canonical exam-end flow: timer expires or student submits →
    backend marks completed → any future login attempt returns state='completed'.
    """
    from app.models.user import Participant
    p = Participant(token="ENDFLOW1", name="End User", identifier="e001",
                    group="adaptive", intervention="proactive", status="unused")
    db_session.add(p)
    await db_session.commit()

    await client.post("/users/", json={"user_id": "ENDFLOW1"})
    await client.post("/session/start", json={"user_id": "ENDFLOW1", "session_id": "sess-end"})
    await client.post("/session/submit", json={"user_id": "ENDFLOW1", "session_id": "sess-end"})

    res = await client.post("/participants/login", json={"token": "ENDFLOW1"})
    assert res.status_code == 200
    assert res.json()["state"] == "completed"


async def test_heartbeat_returns_timer_fields(client):
    """Heartbeat must include exam_start_ms/exam_duration_ms so the frontend can reconcile
    its local countdown (Stage 2 — needed for bulk timer extension to reach an open tab)."""
    await client.post("/users/", json={"user_id": "hb_fields_01"})
    start_res = await client.post("/session/start", json={
        "user_id": "hb_fields_01",
        "session_id": "sess-hbfields"
    })
    start_data = start_res.json()

    res = await client.post("/session/heartbeat",
                            json={"user_id": "hb_fields_01", "session_id": "sess-hbfields"})
    assert res.status_code == 200
    data = res.json()
    assert data["exam_start_ms"] == start_data["exam_start_ms"]
    assert data["exam_duration_ms"] == start_data["exam_duration_ms"]


async def test_heartbeat_reflects_bulk_timer_extension(client, db_session):
    """After a bulk extension (admin_ops.extend_all_exam_timers-shaped UPDATE) widens
    exam_duration_ms, the next heartbeat must report the larger ms_remaining and the new
    exam_duration_ms — this is the server half of the frontend's reconciliation chain."""
    await client.post("/users/", json={"user_id": "hb_extend_01"})
    await client.post("/session/start", json={
        "user_id": "hb_extend_01",
        "session_id": "sess-hbextend"
    })

    before = await client.post("/session/heartbeat",
                               json={"user_id": "hb_extend_01", "session_id": "sess-hbextend"})
    ms_before = before.json()["ms_remaining"]

    extra_ms = 10 * 60 * 1000
    await db_session.execute(
        text("UPDATE exam_sessions SET exam_duration_ms = exam_duration_ms + :extra "
             "WHERE user_id = 'hb_extend_01' AND submitted_at IS NULL"),
        {"extra": extra_ms},
    )
    await db_session.commit()

    after = await client.post("/session/heartbeat",
                              json={"user_id": "hb_extend_01", "session_id": "sess-hbextend"})
    after_data = after.json()
    assert after_data["ms_remaining"] > ms_before
    assert after_data["exam_duration_ms"] == settings.exam_duration_ms + extra_ms


async def test_heartbeat_expired_when_duration_reduced(client, db_session):
    """Heartbeat must return expired=True when admin reduces duration below elapsed.

    Frontend polls this every 25 s; when it returns expired=True it redirects
    all active sessions to /results without waiting for the client-side timer.
    """
    await client.post("/users/", json={"user_id": "hb_expire_01"})
    await client.post("/session/start", json={
        "user_id": "hb_expire_01",
        "session_id": "sess-hbexp"
    })

    await db_session.execute(
        text("UPDATE exam_sessions SET exam_duration_ms=1 WHERE user_id='hb_expire_01'")
    )
    await db_session.commit()

    res = await client.post("/session/heartbeat",
                            json={"user_id": "hb_expire_01", "session_id": "sess-hbexp"})
    assert res.status_code == 200
    assert res.json()["expired"] is True
    assert res.json()["ms_remaining"] == 0
