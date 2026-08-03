# tests/test_questions.py
"""Tests for GET /questions/ — verifies correct_answer never appears on the
wire (Stage 1a), and that the endpoint is gated by session ownership like
every other student endpoint (Stage 4.5): before this, the full exam paper
was downloadable by anyone before the exam even opened."""
from app.models.user import Participant
from app.utils.config import settings


async def _create_participant(db, token, status="active", active_session_id=None):
    p = Participant(
        token=token, name="Questions Test", identifier="q001",
        group="adaptive", intervention="proactive", status=status,
        active_session_id=active_session_id,
    )
    db.add(p)
    await db.commit()
    return p


async def test_get_all_questions_excludes_correct_answer(client):
    res = await client.get("/questions/", params={"user_id": "ad_hoc_q_user"})
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 1
    assert "correct_answer" not in body[0]


async def test_get_single_question_excludes_correct_answer(client):
    res = await client.get("/questions/1", params={"user_id": "ad_hoc_q_user"})
    assert res.status_code == 200
    assert "correct_answer" not in res.json()


async def test_get_all_questions_rejects_non_manifest_user_when_gate_on(client, monkeypatch):
    """With the manifest gate on (production default), a non-manifest
    user_id cannot download the question paper at all."""
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.get("/questions/", params={"user_id": "attacker-no-token"})
    assert res.status_code == 403


async def test_get_all_questions_rejects_mismatched_session_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    await _create_participant(db_session, token="QGATEMIS1", active_session_id="sess-real")
    res = await client.get("/questions/", params={"user_id": "QGATEMIS1", "session_id": "sess-attacker"})
    assert res.status_code == 403


async def test_get_all_questions_accepts_matching_session_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    await _create_participant(db_session, token="QGATEOK01", active_session_id="sess-real")
    res = await client.get("/questions/", params={"user_id": "QGATEOK01", "session_id": "sess-real"})
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 1
    assert "correct_answer" not in body[0]


async def test_get_all_questions_missing_user_id_rejected(client):
    """user_id is a required query param now, not an optional add-on."""
    res = await client.get("/questions/")
    assert res.status_code == 422
