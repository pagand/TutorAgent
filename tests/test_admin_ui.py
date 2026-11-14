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
import io
import json
import sqlite3
import zipfile

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text

from app.admin import queries as admin_queries
from app.endpoints import admin_ui
from app.services.llm_quota import CAP_GLOBAL_KEY, CAP_USER_KEY, get_cap_overrides, get_effective_caps
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


async def _insert_participant(db_session, user_id, status="unused", active_session_id=None,
                               last_seen_at=None, chat_enabled=True, chatiq_enabled=True):
    # name, identifier, "group", intervention, chat_enabled and chatiq_enabled are
    # NOT NULL with no server-side default on the Participant model (app/models/user.py)
    # - the queries under test never read most of them, but the insert fails without
    # them since a raw text() INSERT bypasses the ORM's Python-side `default=`.
    # "group" is a SQL reserved word, quoted accordingly.
    await db_session.execute(
        text('INSERT INTO participants (token, name, identifier, "group", intervention, '
             "chat_enabled, chatiq_enabled, status, active_session_id, last_seen_at) "
             'VALUES (:token, :name, :identifier, :group_val, :intervention, '
             ":chat_enabled, :chatiq_enabled, :status, :active_session_id, :last_seen_at)"),
        {"token": user_id, "name": "Test Student", "identifier": user_id,
         "group_val": "adaptive", "intervention": "proactive",
         "chat_enabled": chat_enabled, "chatiq_enabled": chatiq_enabled,
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
    # The roster (and its "No users yet" empty state) lives on /admin/students
    # now, not the Exam tab - see the _TABS reordering in app/endpoints/admin_ui.py.
    response = await client.get("/admin/students")
    assert response.status_code == 200
    assert "No users yet" in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_home_with_users(client, db_session, seeded_user, stub_llm_usage):
    await _insert_interaction(db_session, seeded_user)
    response = await client.get("/admin/students")
    assert response.status_code == 200
    assert seeded_user in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_students_shows_chat_and_chatiq_flags(client, db_session, seeded_user, stub_llm_usage):
    """The Students tab roster must show both new per-participant flags,
    ChatIQ rendered as a colored on/off tag."""
    await _insert_participant(db_session, seeded_user, chat_enabled=True, chatiq_enabled=False)
    response = await client.get("/admin/students")
    assert response.status_code == 200
    assert '<span class="offline">ChatIQ off</span>' in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_students_counts_page_leave_per_user(client, db_session, seeded_user, stub_llm_usage):
    """The Students roster counts page_leave rows per user: 2 for one, 0 for another."""
    other = "no_leaves_user"
    await _insert_user(db_session, other)
    for _ in range(2):
        await db_session.execute(
            text("INSERT INTO user_action_logs (user_id, session_id, action_type, action_data) "
                 "VALUES (:u, 's1', 'page_leave', '{}')"),
            {"u": seeded_user},
        )
    await db_session.commit()
    rows = {r["user_id"]: r for r in await admin_queries.get_all_users_summary(db_session)}
    assert rows[seeded_user]["page_leaves"] == 2
    assert rows[other]["page_leaves"] == 0
    response = await client.get("/admin/students")
    assert response.status_code == 200
    assert "<th>left_page</th>" in response.text


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
    # Manage is the default tab; KPIs live under Overview now.
    overview = await client.get(f"/admin/user/{seeded_user}?tab=overview")
    assert overview.status_code == 200
    assert "Key Performance Indicators" in overview.text


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

    # Action Log moved to its own tab, so both requests must ask for it.
    unfiltered = await client.get(f"/admin/user/{seeded_user}?tab=actions")
    assert "<td>question_view</td>" in unfiltered.text
    assert "<td>hint_request</td>" in unfiltered.text

    filtered = await client.get(f"/admin/user/{seeded_user}?tab=actions&action_type=hint_request")
    assert filtered.status_code == 200
    assert "<td>hint_request</td>" in filtered.text
    assert "<td>question_view</td>" not in filtered.text


# --- Timer and lock actions ---

@pytest.mark.asyncio
async def test_timer_reset(client, db_session, seeded_user):
    await _insert_exam_session(db_session, seeded_user, exam_start_ms=1000, exam_duration_ms=600000,
                                submitted_at=datetime.datetime.utcnow())
    response = await client.post(f"/admin/user/{seeded_user}/timer/reset", headers={"Origin": "http://test"})
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
    response = await client.post(f"/admin/user/{seeded_user}/timer/extend", data={"extra_minutes": "10"},
                                  headers={"Origin": "http://test"})
    assert response.status_code == 303
    row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id=:uid"), {"uid": seeded_user}
    )).mappings().first()
    assert row["exam_duration_ms"] == 600000 + 10 * 60 * 1000


@pytest.mark.asyncio
async def test_session_lock_clear(client, db_session, seeded_user):
    await _insert_participant(db_session, seeded_user, status="active", active_session_id="dev-123",
                               last_seen_at=datetime.datetime.utcnow())
    response = await client.post(f"/admin/user/{seeded_user}/session-lock/clear", headers={"Origin": "http://test"})
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
        f"/admin/user/{seeded_user}/progress/reset", data={"confirm_token": "wrong-token"},
        headers={"Origin": "http://test"},
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
        f"/admin/user/{seeded_user}/progress/reset", data={"confirm_token": seeded_user},
        headers={"Origin": "http://test"},
    )
    assert response.status_code == 303
    count = (await db_session.execute(
        text("SELECT COUNT(*) FROM interaction_logs WHERE user_id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_delete_user_rejects_mismatched_confirm(client, db_session, seeded_user):
    response = await client.post(
        f"/admin/user/{seeded_user}/delete", data={"confirm_token": "wrong-token"},
        headers={"Origin": "http://test"},
    )
    assert response.status_code == 400
    exists = (await db_session.execute(
        text("SELECT COUNT(*) FROM users WHERE id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert exists == 1


@pytest.mark.asyncio
async def test_delete_user_succeeds_on_match(client, db_session, seeded_user):
    response = await client.post(
        f"/admin/user/{seeded_user}/delete", data={"confirm_token": seeded_user},
        headers={"Origin": "http://test"},
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

    response = await client.post("/admin/exam/extend-all", data={"extra_minutes": "5"},
                                  headers={"Origin": "http://test"})
    assert response.status_code == 303

    active_row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id='active-user'")
    )).mappings().first()
    submitted_row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id='submitted-user'")
    )).mappings().first()
    assert active_row["exam_duration_ms"] == 600000 + 5 * 60 * 1000
    assert submitted_row["exam_duration_ms"] == 600000


# --- CSRF / same-origin protection ---

@pytest.mark.asyncio
async def test_csrf_matching_origin_succeeds(client, db_session):
    await _insert_user(db_session, "csrf-ok-user")
    await _insert_exam_session(db_session, "csrf-ok-user", exam_start_ms=1000, exam_duration_ms=600000)
    response = await client.post("/admin/exam/extend-all", data={"extra_minutes": "5"},
                                  headers={"Origin": "http://test"})
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_csrf_no_origin_no_referer_succeeds(client, db_session):
    """The documented ops-script path: a non-browser client sends neither header."""
    await _insert_user(db_session, "csrf-noheader-user")
    await _insert_exam_session(db_session, "csrf-noheader-user", exam_start_ms=1000, exam_duration_ms=600000)
    response = await client.post("/admin/exam/extend-all", data={"extra_minutes": "5"})
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_csrf_foreign_origin_rejects_extend_all(client, db_session):
    await _insert_user(db_session, "csrf-victim-user")
    await _insert_exam_session(db_session, "csrf-victim-user", exam_start_ms=1000, exam_duration_ms=600000)
    response = await client.post("/admin/exam/extend-all", data={"extra_minutes": "5"},
                                  headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    row = (await db_session.execute(
        text("SELECT exam_duration_ms FROM exam_sessions WHERE user_id='csrf-victim-user'")
    )).mappings().first()
    assert row["exam_duration_ms"] == 600000


@pytest.mark.asyncio
async def test_csrf_foreign_origin_rejects_delete_user(client, db_session, seeded_user):
    response = await client.post(
        f"/admin/user/{seeded_user}/delete", data={"confirm_token": seeded_user},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    exists = (await db_session.execute(
        text("SELECT COUNT(*) FROM users WHERE id=:uid"), {"uid": seeded_user}
    )).scalar_one()
    assert exists == 1


@pytest.mark.asyncio
async def test_csrf_foreign_referer_rejects_timer_reset(client, db_session, seeded_user):
    """Referer is checked when Origin is absent (older browsers / some POSTs omit Origin)."""
    await _insert_exam_session(db_session, seeded_user, exam_start_ms=1000, exam_duration_ms=600000,
                                submitted_at=datetime.datetime.utcnow())
    response = await client.post(
        f"/admin/user/{seeded_user}/timer/reset",
        headers={"Referer": "http://evil.example/attack.html"},
    )
    assert response.status_code == 403
    row = (await db_session.execute(
        text("SELECT exam_start_ms, submitted_at FROM exam_sessions WHERE user_id=:uid"),
        {"uid": seeded_user},
    )).mappings().first()
    assert row["exam_start_ms"] == 1000
    assert row["submitted_at"] is not None


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
async def test_export_download_interaction_logs_includes_confidence(client, db_session, seeded_user):
    """The confidence column (Feature 1) must flow through the generic
    export path: the column header and the stored value both appear."""
    await db_session.execute(
        text("INSERT INTO interaction_logs (user_id, timestamp, question_id, skill, user_answer, "
             "is_correct, hint_shown, hint_style_used, hint_text, user_feedback_rating, bkt_change, "
             "time_taken_ms, confidence) "
             "VALUES (:user_id, :timestamp, :question_id, :skill, :user_answer, :is_correct, "
             ":hint_shown, :hint_style_used, :hint_text, :user_feedback_rating, :bkt_change, "
             ":time_taken_ms, :confidence)"),
        {
            "user_id": seeded_user, "timestamp": datetime.datetime.utcnow(),
            "question_id": 5, "skill": "confidence-test", "user_answer": "A",
            "is_correct": True, "hint_shown": False, "hint_style_used": None,
            "hint_text": None, "user_feedback_rating": None, "bkt_change": 0.05,
            "time_taken_ms": 1000, "confidence": 8,
        },
    )
    await db_session.commit()

    response = await client.get("/admin/export/download", params={"log_type": "Interaction Logs"})
    assert response.status_code == 200
    assert "confidence" in response.text.splitlines()[0]
    assert ",8,,\r\n" in response.text or ",8,,\n" in response.text


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


# --- Export: all log types, exclude users ---

async def _seed_state_tables(db_session, uid):
    await _insert_exam_session(db_session, uid, 1000, 3600000)
    await db_session.execute(
        text("INSERT INTO skill_mastery (user_id, skill_id, mastery_level, consecutive_errors, last_updated, "
             "consecutive_skips) VALUES (:u, 'ratios', 0.5, 0, :ts, 0)"),
        {"u": uid, "ts": datetime.datetime(2026, 1, 1, 12, 0, 0)},
    )
    await db_session.commit()


async def _insert_llm_usage(db_session, uid, created_at):
    await db_session.execute(
        text("INSERT INTO llm_usage_log (user_id, endpoint, created_at) VALUES (:u, 'hint', :ts)"),
        {"u": uid, "ts": created_at},
    )
    await db_session.commit()


async def _seed_two_users_all_logs(db_session):
    for uid, name in (("tok-keep", "keeper"), ("tok-drop", "dropper")):
        await _insert_user(db_session, uid)
        await _insert_participant(db_session, uid)
        await db_session.execute(text("UPDATE participants SET name = :n WHERE token = :t"), {"n": name, "t": uid})
        await _insert_interaction(db_session, uid, skill=f"skill-{uid}")
        await _insert_action_log(db_session, uid, action_type="question_view")
        await db_session.execute(
            text("INSERT INTO chat_logs (user_id, session_id, question_number, timestamp, user_message, tutor_response) "
                 "VALUES (:u, 's1', 1, :ts, :m, 'reply')"),
            {"u": uid, "ts": datetime.datetime.utcnow(), "m": f"msg-{uid}"},
        )
        await db_session.execute(
            text("INSERT INTO intervention_logs (user_id, session_id, question_number, timestamp, "
                 "time_on_question_ms, reason) VALUES (:u, 's1', 1, :ts, 1000, 'time_spent')"),
            {"u": uid, "ts": datetime.datetime.utcnow()},
        )
        await _seed_state_tables(db_session, uid)
        await _insert_llm_usage(db_session, uid, datetime.datetime.utcnow())
    await db_session.commit()


def _zip_entries(response):
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    return {n: zf.read(n).decode() for n in zf.namelist()}


_ZIP_FILES = ["action_logs.csv", "chat_logs.csv", "exam_sessions.csv", "interaction_logs.csv",
              "intervention_logs.csv", "llm_usage_log.csv", "participants.csv", "skill_mastery.csv", "users.csv"]


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_all_log_types_returns_zip_of_nine_csvs(client, db_session):
    await _seed_two_users_all_logs(db_session)
    response = await client.get("/admin/export/download", params={"log_type": "All log types"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="all_logs.zip"' in response.headers["content-disposition"]
    entries = _zip_entries(response)
    assert sorted(entries) == _ZIP_FILES
    for log_type, name in (("Interaction Logs", "interaction_logs.csv"), ("Chat Logs", "chat_logs.csv"),
                           ("Intervention Logs", "intervention_logs.csv"), ("Action Logs", "action_logs.csv")):
        lines = entries[name].splitlines()
        assert lines[0] == ",".join(admin_ui.EXPORT_COLUMNS[log_type])
        assert len(lines) == 3
        single = await client.get("/admin/export/download", params={"log_type": log_type})
        assert single.text == entries[name]


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_zip_raw_table_headers_and_rows(client, db_session):
    await _seed_two_users_all_logs(db_session)
    entries = _zip_entries(await client.get("/admin/export/download", params={"log_type": "All log types"}))
    assert entries["participants.csv"].splitlines()[0] == (
        "token,name,identifier,group,intervention,status,active_session_id,last_seen_at,started_at,"
        "chat_enabled,chatiq_enabled")
    assert entries["users.csv"].splitlines()[0] == "id,created_at,preferences,feedback_scores"
    assert entries["exam_sessions.csv"].splitlines()[0] == (
        "id,user_id,session_id,exam_start_ms,exam_duration_ms,created_at,submitted_at")
    assert entries["skill_mastery.csv"].splitlines()[0] == (
        "id,user_id,skill_id,mastery_level,consecutive_errors,last_updated,consecutive_skips")
    assert entries["llm_usage_log.csv"].splitlines()[0] == "id,user_id,endpoint,created_at"
    for name in ("participants.csv", "users.csv", "exam_sessions.csv", "skill_mastery.csv", "llm_usage_log.csv"):
        assert len(entries[name].splitlines()) == 3
    assert "2026-01-01T12:00:00" in entries["skill_mastery.csv"]
    assert '"{""ab_group"": ""adaptive""' in entries["users.csv"]


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_zip_raw_tables_scoped_by_user_and_exclude(client, db_session):
    await _seed_two_users_all_logs(db_session)
    raw = ("participants.csv", "users.csv", "exam_sessions.csv", "skill_mastery.csv", "llm_usage_log.csv")

    scoped = _zip_entries(await client.get("/admin/export/download",
                                           params={"log_type": "All log types", "user_id": "tok-keep"}))
    excluded = _zip_entries(await client.get("/admin/export/download",
                                             params={"log_type": "All log types", "exclude_user": ["tok-drop"]}))
    for entries in (scoped, excluded):
        for name in raw:
            assert len(entries[name].splitlines()) == 2
            assert "tok-keep" in entries[name]
            assert "tok-drop" not in entries[name]


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_zip_participants_without_users_row_omitted(client, db_session):
    await _seed_two_users_all_logs(db_session)
    await _insert_participant(db_session, "tok-unused")
    entries = _zip_entries(await client.get("/admin/export/download", params={"log_type": "All log types"}))
    assert "tok-unused" not in entries["participants.csv"]
    assert len(entries["participants.csv"].splitlines()) == 3


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_zip_date_filter_applies_to_llm_usage_not_state(client, db_session):
    await _insert_user(db_session, "tok-keep")
    await _seed_state_tables(db_session, "tok-keep")
    await _insert_llm_usage(db_session, "tok-keep", datetime.datetime(2026, 2, 1, 10, 0, 0))
    await _insert_llm_usage(db_session, "tok-keep", datetime.datetime(2026, 2, 10, 23, 59, 59))
    await _insert_llm_usage(db_session, "tok-keep", datetime.datetime(2026, 3, 1, 10, 0, 0))
    entries = _zip_entries(await client.get(
        "/admin/export/download",
        params={"log_type": "All log types", "date_from": "2026-02-05", "date_to": "2026-02-10"},
    ))
    usage = entries["llm_usage_log.csv"].splitlines()
    assert len(usage) == 2
    assert "2026-02-10T23:59:59" in usage[1]
    assert len(entries["skill_mastery.csv"].splitlines()) == 2


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_interaction_logs_has_id_attempt_key_and_voided_at(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user, question_id=7)
    await db_session.execute(
        text("UPDATE interaction_logs SET attempt_key = 'key-abc', voided_at = :v WHERE question_id = 7"),
        {"v": datetime.datetime(2026, 4, 2, 9, 30, 0)},
    )
    await db_session.commit()
    response = await client.get("/admin/export/download", params={"log_type": "Interaction Logs"})
    lines = response.text.splitlines()
    header = lines[0].split(",")
    assert header[0] == "id"
    assert header[-2:] == ["attempt_key", "voided_at"]
    assert lines[1].endswith(",key-abc,2026-04-02 09:30:00") or lines[1].endswith(",key-abc,2026-04-02T09:30:00")


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_all_log_types_single_user_filename_and_scope(client, db_session):
    await _seed_two_users_all_logs(db_session)
    response = await client.get("/admin/export/download",
                                params={"log_type": "All log types", "user_id": "tok-keep"})
    assert 'filename="all_logs_tok-keep.zip"' in response.headers["content-disposition"]
    for text_ in _zip_entries(response).values():
        assert "tok-keep" in text_
        assert "tok-drop" not in text_


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_exclude_user_single_csv_and_zip(client, db_session):
    await _seed_two_users_all_logs(db_session)
    single = await client.get("/admin/export/download",
                              params={"log_type": "Interaction Logs", "exclude_user": ["tok-drop"]})
    assert "tok-keep" in single.text
    assert "tok-drop" not in single.text

    response = await client.get("/admin/export/download",
                                params={"log_type": "All log types", "exclude_user": ["tok-drop"]})
    entries = _zip_entries(response)
    assert len(entries) == 9
    for text_ in entries.values():
        assert "tok-keep" in text_
        assert "tok-drop" not in text_


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_exclude_user_ignored_when_user_selected(client, db_session):
    await _seed_two_users_all_logs(db_session)
    response = await client.get(
        "/admin/export/download",
        params={"log_type": "Interaction Logs", "user_id": "tok-drop", "exclude_user": ["tok-drop"]},
    )
    assert "tok-drop" in response.text


@pytest.mark.asyncio
async def test_export_form_has_exclude_checkboxes_with_names(client, db_session):
    await _insert_user(db_session, "U658HD86")
    await _insert_participant(db_session, "U658HD86")
    await db_session.execute(text("UPDATE participants SET name = 'a6' WHERE token = 'U658HD86'"))
    await _insert_user(db_session, "no-participant")
    await db_session.commit()
    response = await client.get("/admin/export")
    assert response.status_code == 200
    assert "Exclude users" in response.text
    assert '<input type="checkbox" name="exclude_user" value="U658HD86"> a6 (U658HD86)' in response.text
    assert '<input type="checkbox" name="exclude_user" value="no-participant"> no-participant<' in response.text
    assert '<option value="U658HD86">a6 (U658HD86)</option>' in response.text
    assert "All log types" in response.text


# --- Skipped: known Postgres-only constructs (see A5 / module docstring) ---

@pytest.mark.skip(reason="update_user_preferences uses Postgres jsonb CAST/|| syntax, not portable to SQLite")
@pytest.mark.asyncio
async def test_update_prefs_not_run_on_sqlite():
    pass


@pytest.mark.skip(reason="get_llm_usage_last_24h uses Postgres NOW() - INTERVAL syntax, not portable to SQLite")
@pytest.mark.asyncio
async def test_llm_usage_not_run_on_sqlite():
    pass


# --- Top-level tabs ---

@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_top_level_tabs_render(client, stub_llm_usage):
    for path in ["/admin/", "/admin/students", "/admin/research", "/admin/health", "/admin/export"]:
        response = await client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"


@pytest.mark.asyncio
async def test_admin_health_requires_no_database(client):
    """The Health tab takes no db dependency at all, on purpose - it must work
    when the DB is the thing broken. No fixture seeds anything here, and the
    stub_llm_usage fixture (which patches around a DB query) is deliberately
    not used, since this route never touches the DB."""
    response = await client.get("/admin/health")
    assert response.status_code == 200
    assert "Server Health" in response.text


# --- Per-student tabs ---

@pytest.mark.asyncio
async def test_admin_user_detail_all_tabs_return_200(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user)
    for tab in ["manage", "overview", "answers", "hints", "chat", "actions", "danger"]:
        response = await client.get(f"/admin/user/{seeded_user}?tab={tab}")
        assert response.status_code == 200, f"tab={tab} returned {response.status_code}"


@pytest.mark.asyncio
async def test_admin_user_detail_unknown_tab_falls_back_to_manage(client, db_session, seeded_user):
    response = await client.get(f"/admin/user/{seeded_user}?tab=bogus")
    assert response.status_code == 200
    assert "Timer Management" in response.text  # Manage-only heading


@pytest.mark.asyncio
async def test_admin_user_detail_tab_scoping_overview_kpis(client, db_session, seeded_user):
    """Content belonging to one tab must be absent from another - without this,
    a regression that renders everything on every tab would pass every other test."""
    await _insert_interaction(db_session, seeded_user)
    overview = await client.get(f"/admin/user/{seeded_user}?tab=overview")
    manage = await client.get(f"/admin/user/{seeded_user}?tab=manage")
    assert "Key Performance Indicators" in overview.text
    assert "Key Performance Indicators" not in manage.text


@pytest.mark.asyncio
async def test_admin_user_detail_tab_scoping_danger_zone(client, db_session, seeded_user):
    danger = await client.get(f"/admin/user/{seeded_user}?tab=danger")
    manage = await client.get(f"/admin/user/{seeded_user}?tab=manage")
    assert "Delete User" in danger.text
    assert "Delete User" not in manage.text


# --- LLM cap override round trip ---

@pytest.mark.asyncio
async def test_llm_cap_override_round_trip(client, db_session):
    response = await client.post(
        "/admin/settings/llm-caps",
        data={"global_cap": "500", "user_cap": "20"},
        headers={"Origin": "http://test"},
    )
    assert response.status_code == 303
    global_cap, user_cap = await get_effective_caps(db_session)
    assert global_cap == 500
    assert user_cap == 20

    clear_response = await client.post("/admin/settings/llm-caps/clear", headers={"Origin": "http://test"})
    assert clear_response.status_code == 303
    global_cap, user_cap = await get_effective_caps(db_session)
    assert global_cap == settings.llm_max_calls_per_day
    assert user_cap == settings.llm_max_calls_per_user_per_day


@pytest.mark.asyncio
async def test_get_cap_overrides_ignores_malformed_value(client, db_session):
    """A malformed value must be ignored with a warning rather than raised - this
    runs on every hint and chat request via reserve_llm_call."""
    await db_session.execute(
        text("INSERT INTO admin_settings (key, value) VALUES (:key, :value)"),
        {"key": CAP_GLOBAL_KEY, "value": "not-an-int"},
    )
    await db_session.commit()
    overrides = await get_cap_overrides(db_session)
    assert CAP_GLOBAL_KEY not in overrides


# --- CSRF coverage for the newer POST routes ---

@pytest.mark.asyncio
async def test_csrf_foreign_origin_rejects_llm_caps(client, db_session):
    response = await client.post(
        "/admin/settings/llm-caps",
        data={"global_cap": "999", "user_cap": "999"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    global_cap, user_cap = await get_effective_caps(db_session)
    assert global_cap == settings.llm_max_calls_per_day
    assert user_cap == settings.llm_max_calls_per_user_per_day


@pytest.mark.asyncio
async def test_csrf_foreign_origin_rejects_question_unlock(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user, question_id=5, is_correct=False)
    await _insert_interaction(db_session, seeded_user, question_id=5, is_correct=False)
    response = await client.post(
        f"/admin/user/{seeded_user}/question/unlock",
        data={"question_id": "5"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    row = (await db_session.execute(
        text("SELECT voided_at FROM interaction_logs WHERE user_id=:uid AND question_id=5"),
        {"uid": seeded_user},
    )).mappings().first()
    assert row["voided_at"] is None


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

# --- Vancouver time display and dual-timestamp export ---

def test_fmt_ts_converts_utc_to_vancouver_with_zone_label():
    from app.endpoints.admin_ui import _fmt_ts
    assert _fmt_ts(datetime.datetime(2026, 7, 1, 21, 9, 24)) == "2026-07-01 14:09:24 PDT"
    assert _fmt_ts(datetime.datetime(2026, 3, 1, 22, 9, 24)) == "2026-03-01 14:09:24 PST"
    aware = datetime.datetime(2026, 7, 1, 21, 9, 24, tzinfo=datetime.timezone.utc)
    assert _fmt_ts(aware) == "2026-07-01 14:09:24 PDT"
    assert _fmt_ts("2026-03-01 22:09:24.5") == "2026-03-01 14:09:24 PST"
    assert _fmt_ts(None) == "-"


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_admin_user_page_shows_pacific_time(client, db_session, seeded_user):
    await _insert_action_log(db_session, seeded_user, action_type="question_view",
                             timestamp=datetime.datetime(2026, 7, 1, 21, 9, 24))
    await _insert_action_log(db_session, seeded_user, action_type="answer_submit",
                             timestamp=datetime.datetime(2026, 3, 1, 22, 9, 24))
    response = await client.get(f"/admin/user/{seeded_user}?tab=actions")
    assert response.status_code == 200
    assert "2026-07-01 14:09:24 PDT" in response.text
    assert "2026-03-01 14:09:24 PST" in response.text


@_SKIP_JSON_ARROW
@pytest.mark.asyncio
async def test_export_has_utc_and_pt_timestamp_columns(client, db_session, seeded_user):
    await _insert_interaction(db_session, seeded_user, timestamp=datetime.datetime(2026, 7, 1, 21, 9, 24, 391400))
    await _insert_interaction(db_session, seeded_user, timestamp=datetime.datetime(2026, 3, 1, 22, 9, 24))
    response = await client.get("/admin/export/download", params={"log_type": "Interaction Logs"})
    lines = response.text.splitlines()
    assert lines[0].startswith("id,timestamp_utc,timestamp_pt,user_id")
    assert "timestamp," not in lines[0]
    body = response.text
    assert "2026-07-01T21:09:24.391400Z,2026-07-01T14:09:24.391400-07:00" in body
    assert "2026-03-01T22:09:24Z,2026-03-01T14:09:24-08:00" in body
    for log_type in ("Chat Logs", "Intervention Logs", "Action Logs"):
        r = await client.get("/admin/export/download", params={"log_type": log_type})
        assert r.text.splitlines()[0].startswith("timestamp_utc,timestamp_pt,")
