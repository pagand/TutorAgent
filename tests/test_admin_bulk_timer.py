# tests/test_admin_bulk_timer.py
# Tests for app/admin/queries.py — the bulk timer extension used to
# recover all students at once after an outage (PRELAUNCH_CHECKLIST.md
# section B's core blocker for the resume requirement). Uses the shared
# async db_session fixture from tests/conftest.py (in-memory SQLite),
# matching the rest of the async test suite.
import pytest
from sqlalchemy import select

from app.models.user import User, ExamSession
from app.admin.queries import count_active_sessions, extend_all_exam_timers


async def _seed(db_session, user_id, duration_ms, submitted_at=None):
    db_session.add(User(id=user_id, preferences={"ab_group": "adaptive"}, feedback_scores={}))
    db_session.add(ExamSession(
        user_id=user_id, session_id=f"sess-{user_id}",
        exam_start_ms=1_700_000_000_000, exam_duration_ms=duration_ms,
        submitted_at=submitted_at,
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_extend_all_exam_timers_only_touches_unsubmitted(db_session):
    await _seed(db_session, "active_1", 25 * 60 * 1000)
    await _seed(db_session, "active_2", 25 * 60 * 1000)
    await _seed(db_session, "submitted_1", 25 * 60 * 1000, submitted_at=1_700_001_000_000)

    affected = await extend_all_exam_timers(db_session, 10)
    assert affected == 2

    result = await db_session.execute(select(ExamSession))
    durations = {row.user_id: row.exam_duration_ms for row in result.scalars().all()}
    assert durations["active_1"] == 25 * 60 * 1000 + 10 * 60 * 1000
    assert durations["active_2"] == 25 * 60 * 1000 + 10 * 60 * 1000
    assert durations["submitted_1"] == 25 * 60 * 1000  # untouched


@pytest.mark.asyncio
async def test_extend_all_exam_timers_negative_reduces_duration(db_session):
    await _seed(db_session, "active_1", 25 * 60 * 1000)

    affected = await extend_all_exam_timers(db_session, -5)
    assert affected == 1

    result = await db_session.execute(select(ExamSession).filter_by(user_id="active_1"))
    session = result.scalars().first()
    assert session.exam_duration_ms == 25 * 60 * 1000 - 5 * 60 * 1000


@pytest.mark.asyncio
async def test_count_active_sessions(db_session):
    await _seed(db_session, "active_1", 25 * 60 * 1000)
    await _seed(db_session, "active_2", 25 * 60 * 1000)
    await _seed(db_session, "submitted_1", 25 * 60 * 1000, submitted_at=1_700_001_000_000)

    assert await count_active_sessions(db_session) == 2


@pytest.mark.asyncio
async def test_count_active_sessions_zero_when_none_started(db_session):
    assert await count_active_sessions(db_session) == 0
