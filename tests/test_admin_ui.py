"""Tests for the FastAPI admin UI (ADMIN_UI_PORT_PLAN.md, Phase 5).

Uses the client / db_session fixtures from tests/conftest.py (in-memory
SQLite). Seeds rows with raw INSERT statements against the exact
table/column names the ported queries use, rather than the ORM models
suggested in the handoff notes - see ASSUMPTIONS for why.

Two queries are Postgres-only and are skipped outright, per plan: the
preferences jsonb CAST/|| merge, and the NOW() - INTERVAL LLM usage window.
A third construct, the `preferences->>'key'` operator used by most of the
list/log queries, is gated on the SQLite version instead, since modern
SQLite (3.38+) supports the same operator. See ASSUMPTIONS for what that
means for test coverage if the CI SQLite is older.

GET /admin/ (the home page) unconditionally calls the NOW() - INTERVAL
LLM-usage query too, not just a dedicated test - that's a second, indirect
way the same Postgres-only construct blocks SQLite coverage. Skipping the
whole home page outright would have gone dark on everything else that route
renders (KPIs, the users table, Exam Control), so the `stub_llm_usage`
fixture below monkeypatches just that one query out for home-page tests
instead, per A5's "do not weaken the query, fix the test."
"""
import datetime
import json
import sqlite3

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text

from app.admin import queries as admin_queries
from app.utils.config import settings

SQLITE_SUPPORTS_JSON_ARROW = sqlite3.sqlite_version_info >= (3, 38, 0)
_SKIP_JSON_ARROW = pytest.mark.skipif(
    not SQLITE_SUPPORTS_JSON_ARROW,
    reason="SQLite < 3.38 does not support the ->> operator used for preferences->>'ab_group' joins",
)


# --- Seed helpers (raw SQL, see module docstring) ---

async def _insert_user(db_session, user_id, ab_group="adaptive", hint_style="adaptive",
                        intervention="proactive", created_at=None):
    await db_session.execute(
        text("INSERT INTO users (id, created_at, preferences, feedback_scores) "
             "VALUES (:id, :created_at, :preferences, :feedback_scores)"),
        {
            "id": user_id,
            "created_at": created_at or datetime.datetime.utcnow(),
            "preferences": json.dumps({
                "ab_group": ab_group,
                "hint_style_preference": hint_style,
                "intervention_preference": intervention,
            }),
            "feedback_scores": json.dumps({}),
        },
    )
    await db_session.commit()


async def _insert_exam_session(db_session, user_id, exam_start_ms, exam_duration_ms, submitted_at=None):
    await db_session.execute(
        text("INSERT INTO exam_sessions (user_id, exam_start_ms, exam_duration_ms, submitted_at) "
             "VALUES (:user_id, :exam_start_ms, :exam_duration_ms, :submitted_at)"),
        {"user_id": user_id, "exam_start_ms": exam_start_ms,
         "exam_duration_ms": exam_duration_ms, "submitted_at": submitted_at},
    )
    await db_session.commit()


async def _insert_participant(db_session, user_id, status="unused", active_session_id=None, last_seen_at=None):
    # name, identifier, "group" and intervention are NOT NULL with no default
    # on the Participant model (app/models/user.py) - the queries under test
    # never read them, but the insert fails without them. "group" is a SQL
    # reserved word, quoted accordingly.
    await db_session.execute(
        text('INSERT INTO participants (token, name, identifier, "group", intervention, '
             "status, active_session_id, last_seen_at) "
             'VALUES (:token, :name, :identifier, :group_val, :intervention, '
             ":status, :active_session_id, :last_seen_at)"),
        {"token": user_id, "name": "Test Student", "identifier": user_id,
         "group_val": "adaptive", "intervention": "proactive",
         "status": status, "active_session_id": active_session_id,
         "last_seen_at": last_seen_at},
    )
    await db_session.commit()


async def _insert_interaction(db_session, user_id, question_id=1, skill="algebra",
                               is_correct=True, hint_shown=False, timestamp=None):
    await db_session.execute(
        text("INSERT INTO interaction_logs (user_id, timestamp, question_id, skill, user_answer, "
             "is_correct, hint_shown, hint_style_used, hint_text, user_feedback_rating, bkt_change, time_taken_ms) "
             "VALUES (:user_id, :timestamp, :question_id, :skill, :user_answer, :is_correct, "
             ":hint_shown, :hint_style_used, :hint_text, :user_feedback_rating, :bkt_change, :time_taken_ms)"),
        {
            "user_id": user_id, "timestamp": timestamp or datetime.datetime.utcnow(),
            "question_id": question_id, "skill": skill, "user_answer": "A",
            "is_correct": is_correct, "hint_shown": hint_shown, "hint_style_used": None,
            "hint_text": None, "user_feedback_rating": None, "bkt_change": 0.05,
            "time_taken_ms": 1000,
        },
    )
    await db_session.commit()


async def _insert_action_log(db_session, user_id, action_type, question_number=1,
                              timestamp=None, session_id="s1"):
    await db_session.execute(
        text("INSERT INTO user_action_logs (user_id, timestamp, session_id, action_type, question_number, action_data) "
             "VALUES (:user_id, :timestamp, :session_id, :action_type, :question_number, :action_data)"),
        {"user_id": user_id, "timestamp": timestamp or datetime.datetime.utcnow(),
         "session_id": session_id, "action_type": action_type, "question_number": question_number,
         "action_data": json.dumps({})},
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def seeded_user(db_session):
    user_id = "test-user-1"
    await _insert_user(db_session, user_id)
    return user_id


async def _stub_llm_usage(db):
    return {"global_count": 0, "top_users": []}


@pytest.fixture
def stub_llm_usage(monkeypatch):
    """GET /admin/ unconditionally calls get_llm_usage_last_24h, which uses
    Postgres-only NOW() - INTERVAL syntax (see module docstring) - a third
    Postgres-only construct beyond the two A5 flagged, discovered because it
    is reachable from the home page rather than only from a dedicated test.
    Stubbed here so the rest of the home page, which is fully portable and is
    what these tests actually check, still runs on SQLite instead of the
    whole route going untested."""
    monkeypatch.setattr("app.admin.queries.get_llm_usage_last_24h", _stub_llm_usage)


# --- Home page ---

@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_home_empty(client, stub_llm_usage):
    response = await client.get("/admin/")
    assert response.status_code == 200
    assert "No users yet" in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_home_with_users(client, db_session, seeded_user, stub_llm_usage):
    await _insert_interaction(db_session, seeded_user)
    response = await client.get("/admin/")
    assert response.status_code == 200
    assert "System-Wide Analytics" in response.text
    assert seeded_user in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_home_exam_control_shown_without_users(client, stub_llm_usage):
    """Exam Control must stay reachable even when the "No users yet" branch fires."""
    response = await client.get("/admin/")
    assert response.status_code == 200
    assert "Exam Control" in response.text


# --- User detail page ---

@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_user_detail_ok(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user, question_id=7, skill="fractions")
    response = await client.get(f"/admin/user/{seeded_user}")
    assert response.status_code == 200
    assert seeded_user in response.text
    assert "Key Performance Indicators" in response.text


@pytest.mark.asyncio
async def test_admin_user_detail_not_found(client):
    response = await client.get("/admin/user/does-not-exist")
    assert response.status_code == 404


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_user_detail_action_type_filter(client, db_session, seeded_user):
    # The action-type filter <select> always lists every ACTION_TYPES value
    # as an option regardless of the current filter (by design - it's how a
    # proctor picks a different filter), so a bare substring check for
    # "question_view" anywhere on the page is always true, filtered or not.
    # Assert against the actual table cell instead.
    await _insert_action_log(db_session, seeded_user, action_type="question_view")
    await _insert_action_log(db_session, seeded_user, action_type="hint_request")

    unfiltered = await client.get(f"/admin/user/{seeded_user}")
    assert "<td>question_view</td>" in unfiltered.text
    assert "<td>hint_request</td>" in unfiltered.text

    filtered = await client.get(f"/admin/user/{seeded_user}?action_type=hint_request")
    assert filtered.status_code == 200
    assert "<td>hint_request</td>" in filtered.text
    assert "<td>question_view</td>" not in filtered.text


# --- Timer and lock actions ---

@pytest.mark.asyncio
async def test_timer_reset(client, db_session, seeded_user):
    await _insert_exam_session(db_session, seeded_user, exam_start_ms=1000, exam_duration_ms=600000,
                                submitted_at=datetime.datetime.utcnow())
    response = await client.post(f"/admin/user/{seeded_user}/timer/reset")
    assert response.status_code == 303
    row = (await db_session.execute(
        text("SELECT exam_start_ms, submitted_at FROM exam_sessions WHERE user_id=:uid"),
        {"uid": seeded_user},
    )).mappings().first()
    assert row["exam_start_ms"] > 1000
    assert row["submitted_at"] is None


@pytest.mark.asyncio
async def test_timer_extend(client, db_session, seeded_user):
    await _insert_exam_session(db_session, seeded_user, exam_start_ms=1000, exam_duration_ms=600000)
    response = await client.post(f"/admin/user/{seeded_user}/timer/extend", data={"extra_minutes": "10"})
    assert response.status_code == 303
    row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id=:uid"), {"uid": seeded_user}
    )).mappings().first()
    assert row["exam_duration_ms"] == 600000 + 10 * 60 * 1000


@pytest.mark.asyncio
async def test_session_lock_clear(client, db_session, seeded_user):
    await _insert_participant(db_session, seeded_user, status="active", active_session_id="dev-123",
                               last_seen_at=datetime.datetime.utcnow())
    response = await client.post(f"/admin/user/{seeded_user}/session-lock/clear")
    assert response.status_code == 303
    row = (await db_session.execute(
        text("SELECT active_session_id, last_seen_at FROM participants WHERE token=:uid"), {"uid": seeded_user}
    )).mappings().first()
    assert row["active_session_id"] is None
    assert row["last_seen_at"] is None


# --- Danger zone: confirmation gating ---

@pytest.mark.asyncio
async def test_reset_progress_rejects_mismatched_confirm(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user)
    response = await client.post(
        f"/admin/user/{seeded_user}/progress/reset", data={"confirm_token": "wrong-token"}
    )
    assert response.status_code == 400
    count = (await db_session.execute(
        text("SELECT COUNT(*) FROM interaction_logs WHERE user_id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_reset_progress_succeeds_on_match(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user)
    response = await client.post(
        f"/admin/user/{seeded_user}/progress/reset", data={"confirm_token": seeded_user}
    )
    assert response.status_code == 303
    count = (await db_session.execute(
        text("SELECT COUNT(*) FROM interaction_logs WHERE user_id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_delete_user_rejects_mismatched_confirm(client, db_session, seeded_user):
    response = await client.post(
        f"/admin/user/{seeded_user}/delete", data={"confirm_token": "wrong-token"}
    )
    assert response.status_code == 400
    exists = (await db_session.execute(
        text("SELECT COUNT(*) FROM users WHERE id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert exists == 1


@pytest.mark.asyncio
async def test_delete_user_succeeds_on_match(client, db_session, seeded_user):
    response = await client.post(
        f"/admin/user/{seeded_user}/delete", data={"confirm_token": seeded_user}
    )
    assert response.status_code == 303
    exists = (await db_session.execute(
        text("SELECT COUNT(*) FROM users WHERE id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert exists == 0


# --- Bulk exam-wide extension ---

@pytest.mark.asyncio
async def test_count_active_sessions(db_session, seeded_user):
    await _insert_exam_session(db_session, seeded_user, exam_start_ms=1000, exam_duration_ms=600000)
    count = await admin_queries.count_active_sessions(db_session)
    assert count == 1


@pytest.mark.asyncio
async def test_extend_all_exam_timers_skips_submitted(client, db_session):
    await _insert_user(db_session, "active-user")
    await _insert_user(db_session, "submitted-user")
    await _insert_exam_session(db_session, "active-user", exam_start_ms=1000, exam_duration_ms=600000)
    await _insert_exam_session(db_session, "submitted-user", exam_start_ms=1000, exam_duration_ms=600000,
                                submitted_at=datetime.datetime.utcnow())

    response = await client.post("/admin/exam/extend-all", data={"extra_minutes": "5"})
    assert response.status_code == 303

    active_row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id='active-user'")
    )).mappings().first()
    submitted_row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id='submitted-user'")
    )).mappings().first()
    assert active_row["exam_duration_ms"] == 600000 + 5 * 60 * 1000
    assert submitted_row["exam_duration_ms"] == 600000


# --- Export ---

@pytest.mark.asyncio
async def test_export_form_ok(client):
    response = await client.get("/admin/export")
    assert response.status_code == 200
    assert "Export Data" in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_download_interaction_logs(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user, question_id=3, skill="ratios")
    response = await client.get("/admin/export/download", params={"log_type": "Interaction Logs"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert seeded_user in response.text
    assert "ratios" in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_download_action_logs_filtered_by_action_type(client, db_session, seeded_user):
    await _insert_action_log(db_session, seeded_user, action_type="question_view")
    await _insert_action_log(db_session, seeded_user, action_type="answer_submit")
    response = await client.get(
        "/admin/export/download",
        params={"log_type": "Action Logs", "action_type": "answer_submit"},
    )
    assert response.status_code == 200
    assert "answer_submit" in response.text
    assert "question_view" not in response.text


# --- Skipped: known Postgres-only constructs (see A5 / module docstring) ---

@pytest.mark.skip(reason="update_user_preferences uses Postgres jsonb CAST/|| syntax, not portable to SQLite")
@pytest.mark.asyncio
async def test_update_prefs_not_run_on_sqlite():
    pass


@pytest.mark.skip(reason="get_llm_usage_last_24h uses Postgres NOW() - INTERVAL syntax, not portable to SQLite")
@pytest.mark.asyncio
async def test_llm_usage_not_run_on_sqlite():
    pass


# --- API key exemption scoping ---

@pytest.mark.asyncio
async def test_admin_exempt_from_api_key_while_other_paths_401(client, stub_llm_usage):
    original = settings.api_key
    settings.api_key = SecretStr("test-key")
    try:
        admin_response = await client.get("/admin/")
        assert admin_response.status_code != 401

        non_admin_response = await client.get("/nonexistent-admin-exemption-check")
        assert non_admin_response.status_code == 401
    finally:
        settings.api_key = original