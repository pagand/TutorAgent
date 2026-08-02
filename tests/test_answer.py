# tests/test_answer.py
"""
Tests for POST /answer/ — correctness leak, idempotency, and the per-question
attempt cap (Stage 1a).

The shared `client` fixture (tests/conftest.py) mocks question_service so ANY
question_number resolves to the same underlying question data: question_type
"multiple_choice", correct_answer "2", skill "Networking". The endpoint keys
InteractionLog rows off request.question_number (not the mocked question
object's own field), so distinct question_number values in these tests address
genuinely distinct question_id rows even though the mock ignores its input.
"""
from sqlalchemy import select
from app.models.user import InteractionLog, SkillMastery


async def _create_user(client, user_id):
    await client.post("/users/", json={"user_id": user_id})


def _payload(user_id, question_number, attempt_key, user_answer=None, skipped=False):
    return {
        "user_id": user_id,
        "question_number": question_number,
        "attempt_key": attempt_key,
        "user_answer": user_answer,
        "skipped": skipped,
    }


async def test_correct_answer_no_leak(client):
    await _create_user(client, "ans_correct_01")
    res = await client.post("/answer/", json=_payload("ans_correct_01", 1, "k1", user_answer="2"))
    assert res.status_code == 200
    body = res.json()
    assert body["correct"] is True
    assert "correct_answer" not in body


async def test_wrong_answer_no_leak(client):
    await _create_user(client, "ans_wrong_01")
    res = await client.post("/answer/", json=_payload("ans_wrong_01", 1, "k1", user_answer="1"))
    assert res.status_code == 200
    body = res.json()
    assert body["correct"] is False
    assert "correct_answer" not in body


async def test_skip_no_leak(client):
    await _create_user(client, "ans_skip_01")
    res = await client.post("/answer/", json=_payload("ans_skip_01", 1, "k1", skipped=True))
    assert res.status_code == 200
    assert "correct_answer" not in res.json()


async def test_idempotent_retry_same_attempt_key_no_duplicate_log(client, db_session):
    user_id = "ans_idem_01"
    await _create_user(client, user_id)

    r1 = await client.post("/answer/", json=_payload(user_id, 1, "same-key", user_answer="1"))
    r2 = await client.post("/answer/", json=_payload(user_id, 1, "same-key", user_answer="1"))

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["correct"] == r2.json()["correct"]
    assert r1.json()["current_mastery"] == r2.json()["current_mastery"]

    result = await db_session.execute(select(InteractionLog).filter_by(user_id=user_id, question_id=1))
    logs = result.scalars().all()
    assert len(logs) == 1


async def test_idempotent_retry_does_not_double_increment_consecutive_errors(client, db_session):
    user_id = "ans_idem_02"
    await _create_user(client, user_id)

    await client.post("/answer/", json=_payload(user_id, 1, "same-key", user_answer="1"))
    await client.post("/answer/", json=_payload(user_id, 1, "same-key", user_answer="1"))

    result = await db_session.execute(select(SkillMastery).filter_by(user_id=user_id, skill_id="Networking"))
    skill_mastery = result.scalars().first()
    assert skill_mastery.consecutive_errors == 1


async def test_new_attempt_key_creates_second_real_attempt(client, db_session):
    user_id = "ans_newkey_01"
    await _create_user(client, user_id)

    await client.post("/answer/", json=_payload(user_id, 1, "key-1", user_answer="1"))
    await client.post("/answer/", json=_payload(user_id, 1, "key-2", user_answer="3"))

    result = await db_session.execute(select(InteractionLog).filter_by(user_id=user_id, question_id=1))
    logs = result.scalars().all()
    assert len(logs) == 2


async def test_third_attempt_after_two_wrong_rejected(client, db_session):
    user_id = "ans_cap_01"
    await _create_user(client, user_id)

    await client.post("/answer/", json=_payload(user_id, 1, "key-1", user_answer="1"))
    await client.post("/answer/", json=_payload(user_id, 1, "key-2", user_answer="3"))
    res = await client.post("/answer/", json=_payload(user_id, 1, "key-3", user_answer="4"))

    assert res.status_code == 409

    result = await db_session.execute(select(InteractionLog).filter_by(user_id=user_id, question_id=1))
    logs = result.scalars().all()
    assert len(logs) == 2

    sm_result = await db_session.execute(select(SkillMastery).filter_by(user_id=user_id, skill_id="Networking"))
    skill_mastery = sm_result.scalars().first()
    assert skill_mastery.consecutive_errors == 2


async def test_third_attempt_rejected_even_as_skip(client):
    user_id = "ans_cap_02"
    await _create_user(client, user_id)

    await client.post("/answer/", json=_payload(user_id, 1, "key-1", user_answer="1"))
    await client.post("/answer/", json=_payload(user_id, 1, "key-2", user_answer="3"))
    res = await client.post("/answer/", json=_payload(user_id, 1, "key-3", skipped=True))

    assert res.status_code == 409


async def test_attempt_cap_scoped_per_question_not_per_skill(client):
    """Two wrong attempts against a DIFFERENT question sharing the same skill
    must not lock a fresh, never-attempted question. Regression test for the
    checklist correction: SkillMastery.consecutive_errors is skill-scoped, not
    question-scoped, and must not be used to gate this cap."""
    user_id = "ans_scope_01"
    await _create_user(client, user_id)

    # Two wrong real attempts against question_number=2 (same mocked skill "Networking").
    await client.post("/answer/", json=_payload(user_id, 2, "key-1", user_answer="1"))
    await client.post("/answer/", json=_payload(user_id, 2, "key-2", user_answer="3"))

    # A fresh submission to question_number=1 (never attempted) must be accepted.
    res = await client.post("/answer/", json=_payload(user_id, 1, "key-3", user_answer="2"))
    assert res.status_code == 200
    assert res.json()["correct"] is True


async def test_correct_on_second_attempt_not_blocked_by_wrong_attempt_cap(client):
    """A correct answer on the 2nd attempt is not itself capped by the
    2-wrong-attempts rule (already_correct is only known after this call)."""
    user_id = "ans_correct2_01"
    await _create_user(client, user_id)

    await client.post("/answer/", json=_payload(user_id, 1, "key-1", user_answer="1"))
    res = await client.post("/answer/", json=_payload(user_id, 1, "key-2", user_answer="2"))

    assert res.status_code == 200
    assert res.json()["correct"] is True


async def test_already_correct_question_rejects_further_submissions(client, db_session):
    """Once a question has a correct attempt, it is locked read-only — a further
    fresh-key submission (even a correct one) must be rejected, not silently
    re-graded, matching CLAUDE.md's read-only-once-correct rule."""
    user_id = "ans_lockedcorrect_01"
    await _create_user(client, user_id)

    await client.post("/answer/", json=_payload(user_id, 1, "key-1", user_answer="2"))

    res = await client.post("/answer/", json=_payload(user_id, 1, "key-2", user_answer="2"))
    assert res.status_code == 409

    res_skip = await client.post("/answer/", json=_payload(user_id, 1, "key-3", skipped=True))
    assert res_skip.status_code == 409

    result = await db_session.execute(select(InteractionLog).filter_by(user_id=user_id, question_id=1))
    logs = result.scalars().all()
    assert len(logs) == 1  # no further row inserted by the rejected attempts


async def test_unknown_question_still_404s(client, monkeypatch):
    user_id = "ans_404_01"
    await _create_user(client, user_id)

    from app.services.question_service import question_service
    monkeypatch.setattr(question_service, "get_question_by_id", lambda qid: None)

    res = await client.post("/answer/", json=_payload(user_id, 999, "key-1", user_answer="x"))
    assert res.status_code == 404
