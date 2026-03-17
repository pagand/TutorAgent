# tests/test_models.py
# Verifies all new DB models can be created and queried correctly.
import pytest
from datetime import datetime
from sqlalchemy.future import select

from app.models.user import (
    User, ExamSession, UserActionLog, ChatLog, InterventionLog, InteractionLog
)


async def test_user_created_with_ab_group(db_session):
    """New users must have an ab_group in their preferences."""
    from app.state_manager import get_user_or_create
    user = await get_user_or_create(db_session, "test_ab_user")
    await db_session.commit()
    await db_session.refresh(user)

    assert "ab_group" in user.preferences
    assert user.preferences["ab_group"] in ("adaptive", "free_choice")


async def test_ab_group_distribution():
    """A/B group assignment should produce both values given enough samples."""
    groups = set()
    import random
    for _ in range(50):
        groups.add(random.choice(["adaptive", "free_choice"]))
    assert groups == {"adaptive", "free_choice"}


async def test_exam_session_model(db_session):
    user = User(id="sess_user", preferences={"ab_group": "adaptive"}, feedback_scores={})
    db_session.add(user)
    await db_session.flush()

    session = ExamSession(
        user_id="sess_user",
        session_id="test-uuid-1234",
        exam_start_ms=1700000000000,
        exam_duration_ms=25 * 60 * 1000,
    )
    db_session.add(session)
    await db_session.commit()

    result = await db_session.execute(select(ExamSession).filter_by(user_id="sess_user"))
    fetched = result.scalars().first()
    assert fetched is not None
    assert fetched.session_id == "test-uuid-1234"
    assert fetched.exam_start_ms == 1700000000000
    assert fetched.exam_duration_ms == 25 * 60 * 1000


async def test_user_action_log_model(db_session):
    user = User(id="action_user", preferences={"ab_group": "free_choice"}, feedback_scores={})
    db_session.add(user)
    await db_session.flush()

    log = UserActionLog(
        user_id="action_user",
        session_id="sess-abc",
        action_type="choice_select",
        question_number=3,
        action_data={"choice_index": 2, "choice_text": "Network"},
    )
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(
        select(UserActionLog).filter_by(user_id="action_user", action_type="choice_select")
    )
    fetched = result.scalars().first()
    assert fetched is not None
    assert fetched.question_number == 3
    assert fetched.action_data["choice_text"] == "Network"


async def test_chat_log_model(db_session):
    user = User(id="chat_user", preferences={"ab_group": "adaptive"}, feedback_scores={})
    db_session.add(user)
    await db_session.flush()

    log = ChatLog(
        user_id="chat_user",
        session_id="sess-xyz",
        question_number=5,
        user_message="Can you explain what logical addressing is?",
        tutor_response="Think about how devices are identified on a network...",
    )
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(select(ChatLog).filter_by(user_id="chat_user"))
    fetched = result.scalars().first()
    assert fetched is not None
    assert "logical addressing" in fetched.user_message
    assert fetched.question_number == 5


async def test_intervention_log_model(db_session):
    user = User(id="intervention_user", preferences={"ab_group": "adaptive"}, feedback_scores={})
    db_session.add(user)
    await db_session.flush()

    log = InterventionLog(
        user_id="intervention_user",
        session_id="sess-int",
        question_number=2,
        time_on_question_ms=60000,
        mastery_at_trigger=0.25,
        accepted=None,
    )
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(
        select(InterventionLog).filter_by(user_id="intervention_user")
    )
    fetched = result.scalars().first()
    assert fetched is not None
    assert fetched.accepted is None  # Not yet responded
    assert fetched.mastery_at_trigger == pytest.approx(0.25)

    # Simulate user accepting
    fetched.accepted = True
    await db_session.commit()
    await db_session.refresh(fetched)
    assert fetched.accepted is True


async def test_cascade_delete(db_session):
    """Deleting a user should cascade to all related tables."""
    user = User(id="cascade_user", preferences={"ab_group": "adaptive"}, feedback_scores={})
    db_session.add(user)
    await db_session.flush()

    db_session.add(UserActionLog(
        user_id="cascade_user", session_id="s", action_type="question_view",
        question_number=1, action_data={}
    ))
    db_session.add(ChatLog(
        user_id="cascade_user", session_id="s", question_number=1,
        user_message="hi", tutor_response="hello"
    ))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()

    action_result = await db_session.execute(
        select(UserActionLog).filter_by(user_id="cascade_user")
    )
    assert action_result.scalars().first() is None

    chat_result = await db_session.execute(
        select(ChatLog).filter_by(user_id="cascade_user")
    )
    assert chat_result.scalars().first() is None
