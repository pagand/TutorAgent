# tests/test_participant_gate.py
"""Tests for the manifest-token gate (Stage 4.5), run with
require_participant_token FORCED ON — the production default that the rest
of the suite deliberately opts out of (see conftest.py's client fixture).

This is the file that proves PRELAUNCH_CHECKLIST.md section 0's finding is
closed: before Stage 4.5, POST /users/ created a User row for any string
with no check that a matching Participant existed, and verify_session_owner
was a no-op for that identity by design - so a non-manifest user_id could
create an account, start a live exam clock, and use /chat/ as an unmetered
LLM proxy, with no token at all.

The flag is set inside each test body (not via an autouse fixture) because
the client fixture's own setup unconditionally sets require_participant_token
back to False after fixture instantiation order would otherwise put an
autouse patch first - setting it in the test body runs strictly after all
fixture setup has completed, so it always wins.
"""
from app.models.user import Participant
from app.utils.config import settings


async def _create_participant(db, token, status="active", active_session_id=None):
    p = Participant(
        token=token, name="Gate Test", identifier="gate001",
        group="adaptive", intervention="proactive", status=status,
        active_session_id=active_session_id,
    )
    db.add(p)
    await db.commit()
    return p


# --- Non-manifest user_id: the exact section 0 reproduction ---

async def test_create_user_rejected_for_non_manifest_id(client, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.post("/users/", json={"user_id": "attacker-no-token"})
    assert res.status_code == 403


async def test_session_start_unreachable_without_a_manifest_user(client, monkeypatch):
    """No POST /users/ ever succeeded for this id, so no User row exists -
    the exam clock can never be started for an identity the manifest never
    issued a token for."""
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.post("/session/start", json={
        "user_id": "attacker-no-token", "session_id": "sess-attacker",
    })
    assert res.status_code != 200


async def test_questions_rejected_for_non_manifest_id(client, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.get("/questions/", params={"user_id": "attacker-no-token"})
    assert res.status_code == 403


async def test_hints_rejected_for_non_manifest_id(client, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.post("/hints/", json={
        "user_id": "attacker-no-token", "question_number": 1,
    })
    assert res.status_code == 403


async def test_chat_rejected_for_non_manifest_id(client, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.post("/chat/", json={
        "user_id": "attacker-no-token", "session_id": "sess-attacker",
        "question_number": 1, "message": "What's the answer?", "chat_history": [],
    })
    assert res.status_code == 403


async def test_answer_rejected_for_non_manifest_id(client, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    res = await client.post("/answer/", json={
        "user_id": "attacker-no-token", "question_number": 1,
        "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 403


# --- Manifest token holding the device lock: everything above now works ---

async def test_full_flow_works_for_a_manifest_token(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "require_participant_token", True)
    await _create_participant(db_session, token="GATEOK001", active_session_id="sess-real")

    res = await client.post("/users/", json={"user_id": "GATEOK001"})
    assert res.status_code == 200

    res = await client.post("/session/start", json={
        "user_id": "GATEOK001", "session_id": "sess-real",
    })
    assert res.status_code == 200

    res = await client.get("/questions/", params={"user_id": "GATEOK001", "session_id": "sess-real"})
    assert res.status_code == 200
    assert len(res.json()) >= 1

    res = await client.post("/answer/", json={
        "user_id": "GATEOK001", "session_id": "sess-real",
        "question_number": 1, "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 200

    # /hints/ and /chat/ aren't fully mocked here (that's test_chat.py's job) -
    # the only thing under test is that a manifest token holding the lock
    # gets PAST the authz gate, i.e. never sees a 403.
    res = await client.post("/hints/", json={
        "user_id": "GATEOK001", "session_id": "sess-real", "question_number": 1,
    })
    assert res.status_code != 403

    res = await client.post("/chat/", json={
        "user_id": "GATEOK001", "session_id": "sess-real",
        "question_number": 1, "message": "Can you explain this?", "chat_history": [],
    })
    assert res.status_code != 403


async def test_wrong_session_id_still_rejected_with_gate_on(client, db_session, monkeypatch):
    """The manifest gate doesn't relax the existing per-device lock check -
    a stolen token still needs the real device's session_id."""
    monkeypatch.setattr(settings, "require_participant_token", True)
    await _create_participant(db_session, token="GATEMIS001", active_session_id="sess-real")
    await client.post("/users/", json={"user_id": "GATEMIS001"})

    res = await client.post("/answer/", json={
        "user_id": "GATEMIS001", "session_id": "sess-attacker",
        "question_number": 1, "attempt_key": "k1", "user_answer": "2",
    })
    assert res.status_code == 403
