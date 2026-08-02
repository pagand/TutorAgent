# tests/test_authz.py
"""
Tests for row-level access control (app/utils/authz.py) — Stage 3 hardening.

The device lock claimed by POST /session/start (Participant.active_session_id)
is the only thing binding a request to the student who owns a token. These
tests confirm a mismatched session_id is rejected on a gated endpoint, a
matching one succeeds, participant-less (ad-hoc/dev) user_ids are exempt —
this is what keeps the rest of the suite's ad-hoc users working unmodified —
and a completed participant's own profile read isn't blocked by a stale or
missing session_id (the cross-device /results case).
"""
import pytest

from app.models.user import Participant


async def _create_participant(db, token, status="active", active_session_id=None):
    p = Participant(
        token=token, name="Authz Test", identifier="authz001",
        group="adaptive", intervention="proactive", status=status,
        active_session_id=active_session_id,
    )
    db.add(p)
    await db.commit()
    return p


@pytest.mark.asyncio
async def test_answer_rejects_mismatched_session_id(client, db_session):
    await _create_participant(db_session, token="RLSMIS01", active_session_id="sess-real")
    await client.post("/users/", json={"user_id": "RLSMIS01"})

    res = await client.post("/answer/", json={
        "user_id": "RLSMIS01", "session_id": "sess-attacker",
        "question_number": 1, "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_answer_accepts_matching_session_id(client, db_session):
    await _create_participant(db_session, token="RLSOK001", active_session_id="sess-real")
    await client.post("/users/", json={"user_id": "RLSOK001"})

    res = await client.post("/answer/", json={
        "user_id": "RLSOK001", "session_id": "sess-real",
        "question_number": 1, "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_answer_rejects_missing_session_id_for_participant(client, db_session):
    await _create_participant(db_session, token="RLSNONE1", active_session_id="sess-real")
    await client.post("/users/", json={"user_id": "RLSNONE1"})

    res = await client.post("/answer/", json={
        "user_id": "RLSNONE1",
        "question_number": 1, "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_answer_allows_ad_hoc_user_with_no_participant_row(client):
    """Ad-hoc/dev user_ids with no manifest entry have no lock to enforce."""
    await client.post("/users/", json={"user_id": "ad_hoc_student"})

    res = await client.post("/answer/", json={
        "user_id": "ad_hoc_student",
        "question_number": 1, "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_profile_read_allowed_for_completed_participant_from_any_device(client, db_session):
    """Once completed, profile reads (the /results cross-device case) aren't
    gated on the session_id that happened to claim the lock last."""
    await _create_participant(db_session, token="RLSDONE1", status="completed", active_session_id="sess-old")
    await client.post("/users/", json={"user_id": "RLSDONE1"})

    res = await client.get("/users/RLSDONE1/profile")
    assert res.status_code == 200

    res2 = await client.get("/users/RLSDONE1/profile", params={"session_id": "sess-new-device"})
    assert res2.status_code == 200


@pytest.mark.asyncio
async def test_profile_read_rejected_mid_exam_for_wrong_device(client, db_session):
    """Mid-exam (not completed), profile reads ARE gated — this is the fix
    for the original finding that any token holder could read any
    student's full history and completed_answers."""
    await _create_participant(db_session, token="RLSMID01", status="active", active_session_id="sess-real")
    await client.post("/users/", json={"user_id": "RLSMID01"})

    res = await client.get("/users/RLSMID01/profile", params={"session_id": "sess-attacker"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_bkt_endpoint_returns_200_not_500(client):
    """Regression test for the get_bkt_mastery(session, user_id, skill, default)
    argument-order bug that made this endpoint always 500."""
    await client.post("/users/", json={"user_id": "bkt_user_01"})
    res = await client.get("/users/bkt_user_01/bkt")
    assert res.status_code == 200
    assert isinstance(res.json(), dict)


@pytest.mark.asyncio
async def test_delete_user_endpoint_removed(client):
    """DELETE /users/{id} was removed — zero consumers, and it was an
    unauthenticated destructive IDOR against any participant."""
    await client.post("/users/", json={"user_id": "no_delete_01"})
    res = await client.delete("/users/no_delete_01")
    assert res.status_code == 404
