# tests/test_admin_bulk_timer.py
# Tests for streamlit_app/admin_ops.py — the bulk timer extension used to
# recover all students at once after an outage (PRELAUNCH_CHECKLIST.md
# section B's core blocker for the resume requirement). Uses a plain sync
# SQLite engine rather than the async pytest fixtures in conftest.py, because
# admin_ops (like queries.py) is written for the sync Session Streamlit uses.
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.user import Base, User, ExamSession
from streamlit_app.admin_ops import count_active_sessions, extend_all_exam_timers


@pytest.fixture
def sync_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    engine.dispose()


def _seed(db, user_id, duration_ms, submitted_at=None):
    db.add(User(id=user_id, preferences={"ab_group": "adaptive"}, feedback_scores={}))
    db.add(ExamSession(
        user_id=user_id, session_id=f"sess-{user_id}",
        exam_start_ms=1_700_000_000_000, exam_duration_ms=duration_ms,
        submitted_at=submitted_at,
    ))
    db.commit()


def test_extend_all_exam_timers_only_touches_unsubmitted(sync_db):
    _seed(sync_db, "active_1", 25 * 60 * 1000)
    _seed(sync_db, "active_2", 25 * 60 * 1000)
    _seed(sync_db, "submitted_1", 25 * 60 * 1000, submitted_at=1_700_001_000_000)

    affected = extend_all_exam_timers(sync_db, 10)
    assert affected == 2

    durations = {
        row.user_id: row.exam_duration_ms
        for row in sync_db.query(ExamSession).all()
    }
    assert durations["active_1"] == 25 * 60 * 1000 + 10 * 60 * 1000
    assert durations["active_2"] == 25 * 60 * 1000 + 10 * 60 * 1000
    assert durations["submitted_1"] == 25 * 60 * 1000  # untouched


def test_extend_all_exam_timers_negative_reduces_duration(sync_db):
    _seed(sync_db, "active_1", 25 * 60 * 1000)

    affected = extend_all_exam_timers(sync_db, -5)
    assert affected == 1

    session = sync_db.query(ExamSession).filter_by(user_id="active_1").first()
    assert session.exam_duration_ms == 25 * 60 * 1000 - 5 * 60 * 1000


def test_count_active_sessions(sync_db):
    _seed(sync_db, "active_1", 25 * 60 * 1000)
    _seed(sync_db, "active_2", 25 * 60 * 1000)
    _seed(sync_db, "submitted_1", 25 * 60 * 1000, submitted_at=1_700_001_000_000)

    assert count_active_sessions(sync_db) == 2


def test_count_active_sessions_zero_when_none_started(sync_db):
    assert count_active_sessions(sync_db) == 0
