# tests/test_participants.py
"""
Tests for Phase 2: token-based participant access.

Covers:
- /participants/login state machine (invalid, not_started, resumable, active_elsewhere, completed)
- /session/start 409 enforcement on concurrent device
- /session/submit persists submitted_at
- /session/heartbeat returns submitted=True after submit
- A/B group + intervention sourced from the manifest (Participant row)
"""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from app.models.user import Participant, User, ExamSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_participant(db, token="TESTTKN1", name="Test User",
                               identifier="t001", group="adaptive",
                               intervention="proactive", status="unused",
                               active_session_id=None, last_seen_at=None):
    p = Participant(
        token=token, name=name, identifier=identifier,
        group=group, intervention=intervention, status=status,
        active_session_id=active_session_id, last_seen_at=last_seen_at,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _create_user(db, user_id="TESTTKN1"):
    u = User(id=user_id, preferences={})
    db.add(u)
    await db.commit()
    return u


async def _create_exam_session(db, user_id="TESTTKN1", session_id="sess_a",
                                exam_start_ms=1_700_000_000_000,
                                submitted_at=None):
    es = ExamSession(
        user_id=user_id, session_id=session_id,
        exam_start_ms=exam_start_ms, exam_duration_ms=25 * 60 * 1000,
        submitted_at=submitted_at,
    )
    db.add(es)
    await db.commit()
    return es


# ---------------------------------------------------------------------------
# /participants/login state machine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_invalid_token(client):
    res = await client.post("/participants/login", json={"token": "BADTOKEN"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_login_not_started(client, db_session):
    await _create_participant(db_session, token="NOSTART1", status="unused")
    res = await client.post("/participants/login", json={"token": "NOSTART1"})
    assert res.status_code == 200
    assert res.json()["state"] == "not_started"
    assert res.json()["name"] == "Test User"


@pytest.mark.asyncio
async def test_login_resumable_no_heartbeat(client, db_session):
    """Session exists but participant is not 'active' — should be resumable."""
    await _create_participant(db_session, token="RESUME01", status="unused")
    await _create_user(db_session, user_id="RESUME01")
    await _create_exam_session(db_session, user_id="RESUME01")
    res = await client.post("/participants/login", json={"token": "RESUME01"})
    assert res.status_code == 200
    assert res.json()["state"] == "resumable"


@pytest.mark.asyncio
async def test_login_resumable_stale_heartbeat(client, db_session):
    """Active status but heartbeat is stale (>60 s) — should be resumable."""
    stale_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=120)
    await _create_participant(db_session, token="STALE001", status="active",
                               active_session_id="sess_old", last_seen_at=stale_ts)
    await _create_user(db_session, user_id="STALE001")
    await _create_exam_session(db_session, user_id="STALE001")
    res = await client.post("/participants/login", json={"token": "STALE001"})
    assert res.status_code == 200
    assert res.json()["state"] == "resumable"


@pytest.mark.asyncio
async def test_login_active_elsewhere(client, db_session):
    """Active status with a fresh heartbeat — should be blocked."""
    fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    await _create_participant(db_session, token="ACTIVE01", status="active",
                               active_session_id="sess_other", last_seen_at=fresh_ts)
    await _create_user(db_session, user_id="ACTIVE01")
    await _create_exam_session(db_session, user_id="ACTIVE01")
    res = await client.post("/participants/login", json={"token": "ACTIVE01"})
    assert res.status_code == 200
    assert res.json()["state"] == "active_elsewhere"


@pytest.mark.asyncio
async def test_login_completed_via_participant_status(client, db_session):
    await _create_participant(db_session, token="DONE0001", status="completed")
    await _create_user(db_session, user_id="DONE0001")
    await _create_exam_session(db_session, user_id="DONE0001")
    res = await client.post("/participants/login", json={"token": "DONE0001"})
    assert res.status_code == 200
    assert res.json()["state"] == "completed"


@pytest.mark.asyncio
async def test_login_completed_via_submitted_at(client, db_session):
    """submitted_at on ExamSession also gates as completed."""
    await _create_participant(db_session, token="SUBM0001", status="active")
    await _create_user(db_session, user_id="SUBM0001")
    await _create_exam_session(db_session, user_id="SUBM0001", submitted_at=1_700_000_001_000)
    res = await client.post("/participants/login", json={"token": "SUBM0001"})
    assert res.status_code == 200
    assert res.json()["state"] == "completed"


# ---------------------------------------------------------------------------
# /session/start — concurrent device enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_start_claims_participant(client, db_session):
    """Starting a session marks the participant active and sets active_session_id."""
    from sqlalchemy.future import select
    await _create_participant(db_session, token="CLAIM001", status="unused")
    await _create_user(db_session, user_id="CLAIM001")

    res = await client.post("/session/start", json={"user_id": "CLAIM001", "session_id": "sess_x"})
    assert res.status_code == 200

    db_session.expire_all()
    result = await db_session.execute(select(Participant).filter_by(token="CLAIM001"))
    p = result.scalars().first()
    assert p.status == "active"
    assert p.active_session_id == "sess_x"


@pytest.mark.asyncio
async def test_session_start_same_device_reload_allowed(client, db_session):
    """Same session_id → not a concurrent device; should succeed."""
    fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    await _create_participant(db_session, token="RELOAD01", status="active",
                               active_session_id="sess_same", last_seen_at=fresh_ts)
    await _create_user(db_session, user_id="RELOAD01")
    await _create_exam_session(db_session, user_id="RELOAD01", session_id="sess_same")

    res = await client.post("/session/start", json={"user_id": "RELOAD01", "session_id": "sess_same"})
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_session_start_second_device_blocked(client, db_session):
    """Different session_id with a fresh heartbeat → 409."""
    fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    await _create_participant(db_session, token="BLOCK001", status="active",
                               active_session_id="sess_first", last_seen_at=fresh_ts)
    await _create_user(db_session, user_id="BLOCK001")
    await _create_exam_session(db_session, user_id="BLOCK001", session_id="sess_first")

    res = await client.post("/session/start", json={"user_id": "BLOCK001", "session_id": "sess_second"})
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# /session/submit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_submit_persists_submitted_at(client, db_session):
    from sqlalchemy.future import select
    await _create_participant(db_session, token="SUBMITX1", status="active", active_session_id="sess_submitx1")
    await _create_user(db_session, user_id="SUBMITX1")
    await _create_exam_session(db_session, user_id="SUBMITX1", session_id="sess_submitx1")

    res = await client.post("/session/submit", json={"user_id": "SUBMITX1", "session_id": "sess_submitx1"})
    assert res.status_code == 200
    assert res.json()["submitted"] is True

    db_session.expire_all()
    result = await db_session.execute(select(ExamSession).filter_by(user_id="SUBMITX1"))
    es = result.scalars().first()
    assert es.submitted_at is not None

    result = await db_session.execute(select(Participant).filter_by(token="SUBMITX1"))
    p = result.scalars().first()
    assert p.status == "completed"
    # active_session_id is deliberately left set after submit — GET
    # /users/{id}/profile is gated on it, and a student must still be able
    # to fetch their own profile (e.g. the /results page) right after
    # submitting, from the same device.
    assert p.active_session_id == "sess_submitx1"


@pytest.mark.asyncio
async def test_session_submit_idempotent(client, db_session):
    """Calling /session/submit twice should not raise an error."""
    await _create_participant(db_session, token="IDEM0001", status="active", active_session_id="sess_idem1")
    await _create_user(db_session, user_id="IDEM0001")
    await _create_exam_session(db_session, user_id="IDEM0001", session_id="sess_idem1")

    r1 = await client.post("/session/submit", json={"user_id": "IDEM0001", "session_id": "sess_idem1"})
    r2 = await client.post("/session/submit", json={"user_id": "IDEM0001", "session_id": "sess_idem1"})
    assert r1.status_code == 200
    assert r2.status_code == 200


# ---------------------------------------------------------------------------
# /session/heartbeat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_submitted_true_after_submit(client, db_session):
    await _create_participant(db_session, token="HBEAT001", status="active",
                               active_session_id="sess_hb")
    await _create_user(db_session, user_id="HBEAT001")
    await _create_exam_session(db_session, user_id="HBEAT001", session_id="sess_hb",
                                submitted_at=1_700_000_001_000)

    res = await client.post("/session/heartbeat",
                            json={"user_id": "HBEAT001", "session_id": "sess_hb"})
    assert res.status_code == 200
    assert res.json()["submitted"] is True


@pytest.mark.asyncio
async def test_heartbeat_active_false_on_takeover(client, db_session):
    """Heartbeat from the old session_id after another device claimed → active=False."""
    await _create_participant(db_session, token="TAKEO001", status="active",
                               active_session_id="sess_new")
    await _create_user(db_session, user_id="TAKEO001")
    await _create_exam_session(db_session, user_id="TAKEO001", session_id="sess_new")

    res = await client.post("/session/heartbeat",
                            json={"user_id": "TAKEO001", "session_id": "sess_old"})
    assert res.status_code == 200
    assert res.json()["active"] is False


# ---------------------------------------------------------------------------
# Manifest group sourcing in get_user_or_create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_creation_uses_manifest_group(client, db_session):
    """When a Participant row exists, the created User gets its group/intervention."""
    from sqlalchemy.future import select
    await _create_participant(db_session, token="GRPTEST1", group="free_choice",
                               intervention="manual")

    res = await client.post("/users/", json={"user_id": "GRPTEST1"})
    assert res.status_code == 200

    db_session.expire_all()
    result = await db_session.execute(select(User).filter_by(id="GRPTEST1"))
    u = result.scalars().first()
    assert u.preferences["ab_group"] == "free_choice"
    assert u.preferences["intervention_preference"] == "manual"
