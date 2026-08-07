"""Async admin data layer for the FastAPI admin UI.

Ported from the retired streamlit_app/queries.py and streamlit_app/admin_ops.py
(ADMIN_UI_PORT_PLAN.md, Phase 1). SQL semantics are preserved exactly - the
only changes are sync -> async and pandas.DataFrame -> plain dict/list, so
this module never touches pandas and never blocks the event loop.
"""
import json
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.question_service import question_service
from app.utils.config import settings


def _decode_json(value):
    """Raw text() queries bypass SQLAlchemy's Column(JSON) result processor,
    so a JSON column comes back as the driver's native string rather than a
    decoded dict/list. Values already decoded (e.g. a driver that does apply
    a codec) pass through unchanged."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


class BKTCalculator:
    """Mirrors the production BKT update rule, for trajectory replay only.

    Read-only: this never writes to skill_mastery, it only recomputes a
    display curve from the interaction history that's already in the DB.
    """

    def __init__(self, p_l0: float, p_t: float, p_g: float, p_s: float):
        self.p_l0 = p_l0
        self.p_t = p_t
        self.p_g = p_g
        self.p_s = p_s

    def _calculate_posterior(self, prior_ln: float, is_correct: bool) -> float:
        if is_correct:
            prob_evidence_given_ln = 1.0 - self.p_s
            prob_evidence_given_not_ln = self.p_g
        else:
            prob_evidence_given_ln = self.p_s
            prob_evidence_given_not_ln = 1.0 - self.p_g
        prob_evidence = (prob_evidence_given_ln * prior_ln) + (prob_evidence_given_not_ln * (1.0 - prior_ln))
        if prob_evidence == 0:
            return prior_ln
        posterior = (prob_evidence_given_ln * prior_ln) / prob_evidence
        return max(0.0, min(1.0, posterior))

    def calculate_mastery_update(self, prior_ln_minus_1: float, is_correct: bool) -> float:
        posterior_ln_minus_1 = self._calculate_posterior(prior_ln_minus_1, is_correct)
        new_ln = posterior_ln_minus_1 + (1.0 - posterior_ln_minus_1) * self.p_t
        return max(0.0, min(1.0, new_ln))


bkt_calculator = BKTCalculator(
    p_l0=settings.bkt_p_l0,
    p_t=settings.bkt_p_t,
    p_g=settings.bkt_p_g,
    p_s=settings.bkt_p_s,
)


# --- User queries ---

async def get_all_user_ids(db: AsyncSession) -> list[str]:
    result = await db.execute(text("SELECT id FROM users ORDER BY created_at DESC"))
    return [row[0] for row in result.all()]


async def get_all_users_summary(db: AsyncSession) -> list[dict]:
    """All users with A/B group, creation time, basic stats, and timer info.

    Each log table is aggregated to one row per user before being joined
    onto users, the same way the original query did it, so joining
    interaction_logs and chat_logs directly onto the same user row never
    produces a cartesian product.

    Uses the Postgres `->>'key'` JSON operator on preferences. Not portable
    to older SQLite - see ASSUMPTIONS in the handoff notes.
    """
    query = text("""
        WITH interaction_agg AS (
            SELECT user_id,
                   COUNT(*) AS total_interactions,
                   SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_answers,
                   SUM(CASE WHEN hint_shown THEN 1 ELSE 0 END) AS hints_used
            FROM interaction_logs
            GROUP BY user_id
        ),
        chat_agg AS (
            SELECT user_id, COUNT(*) AS chat_messages
            FROM chat_logs
            GROUP BY user_id
        )
        SELECT
            u.id AS user_id,
            u.created_at,
            u.preferences->>'ab_group' AS ab_group,
            u.preferences->>'hint_style_preference' AS hint_style_pref,
            u.preferences->>'intervention_preference' AS intervention_pref,
            COALESCE(ia.total_interactions, 0) AS total_interactions,
            COALESCE(ia.correct_answers, 0) AS correct_answers,
            COALESCE(ia.hints_used, 0) AS hints_used,
            COALESCE(ca.chat_messages, 0) AS chat_messages,
            es.exam_start_ms,
            es.exam_duration_ms,
            es.submitted_at,
            p.status AS participant_status
        FROM users u
        LEFT JOIN interaction_agg ia ON ia.user_id = u.id
        LEFT JOIN chat_agg ca ON ca.user_id = u.id
        LEFT JOIN exam_sessions es ON es.user_id = u.id
        LEFT JOIN participants p ON p.token = u.id
        ORDER BY u.created_at DESC
    """)
    result = await db.execute(query)
    rows = [dict(r) for r in result.mappings().all()]
    now_ms = int(time.time() * 1000)
    for row in rows:
        if row["exam_start_ms"] is None or row["exam_duration_ms"] is None:
            row["remaining_min"] = None
        else:
            elapsed = now_ms - int(row["exam_start_ms"])
            remaining = max(0, int(row["exam_duration_ms"]) - elapsed)
            row["remaining_min"] = remaining // 60000
        row["submitted"] = row["submitted_at"] is not None
    return rows


async def get_user_profile(db: AsyncSession, user_id: str) -> dict:
    query = text("SELECT id, created_at, preferences, feedback_scores FROM users WHERE id = :user_id")
    result = await db.execute(query, {"user_id": user_id})
    row = result.mappings().first()
    if not row:
        return {}
    profile = dict(row)
    profile["preferences"] = _decode_json(profile["preferences"])
    profile["feedback_scores"] = _decode_json(profile["feedback_scores"])
    return profile


# --- Interaction logs ---

async def get_raw_interaction_history(db: AsyncSession, user_id: str) -> list[dict]:
    """Ascending by timestamp - other functions below rely on that order."""
    query = text("""
        SELECT timestamp, question_id, skill, user_answer, is_correct,
               hint_shown, hint_style_used, hint_text, user_feedback_rating, bkt_change
        FROM interaction_logs
        WHERE user_id = :user_id
        ORDER BY timestamp ASC
    """)
    result = await db.execute(query, {"user_id": user_id})
    return [dict(r) for r in result.mappings().all()]


async def get_interaction_history(db: AsyncSession, user_id: str) -> list[dict]:
    """Descending by timestamp, with question text attached from
    question_service (see ASSUMPTIONS re: question_id vs question_number).
    """
    rows = await get_raw_interaction_history(db, user_id)
    for row in rows:
        question = question_service.get_question_by_id(row["question_id"])
        row["question"] = question.question if question else None
    return sorted(rows, key=lambda r: r["timestamp"], reverse=True)


async def get_all_interaction_logs(db: AsyncSession, user_id: str | None = None) -> list[dict]:
    """All interaction logs, optionally filtered to a single user. Includes ab_group."""
    where = "WHERE il.user_id = :user_id" if user_id else ""
    params = {"user_id": user_id} if user_id else {}
    query = text(f"""
        SELECT il.timestamp, il.user_id,
               u.preferences->>'ab_group' AS ab_group,
               il.question_id, il.skill, il.user_answer, il.is_correct,
               il.hint_shown, il.hint_style_used, il.hint_text,
               il.user_feedback_rating, il.bkt_change, il.time_taken_ms
        FROM interaction_logs il
        JOIN users u ON u.id = il.user_id
        {where}
        ORDER BY il.timestamp DESC
    """)
    result = await db.execute(query, params)
    return [dict(r) for r in result.mappings().all()]


# --- Chat logs ---

async def get_chat_logs(db: AsyncSession, user_id: str | None = None) -> list[dict]:
    where = "WHERE cl.user_id = :user_id" if user_id else ""
    params = {"user_id": user_id} if user_id else {}
    query = text(f"""
        SELECT cl.timestamp, cl.user_id,
               u.preferences->>'ab_group' AS ab_group,
               cl.session_id, cl.question_number, cl.user_message, cl.tutor_response
        FROM chat_logs cl
        JOIN users u ON u.id = cl.user_id
        {where}
        ORDER BY cl.timestamp DESC
    """)
    result = await db.execute(query, params)
    return [dict(r) for r in result.mappings().all()]


# --- Intervention logs ---

async def get_intervention_logs(db: AsyncSession, user_id: str | None = None) -> list[dict]:
    where = "WHERE il.user_id = :user_id" if user_id else ""
    params = {"user_id": user_id} if user_id else {}
    query = text(f"""
        SELECT il.timestamp, il.user_id,
               u.preferences->>'ab_group' AS ab_group,
               il.session_id, il.question_number, il.time_on_question_ms,
               il.mastery_at_trigger, il.reason, il.accepted
        FROM intervention_logs il
        JOIN users u ON u.id = il.user_id
        {where}
        ORDER BY il.timestamp DESC
    """)
    result = await db.execute(query, params)
    return [dict(r) for r in result.mappings().all()]


# --- Action logs ---

async def get_action_logs(db: AsyncSession, user_id: str | None = None,
                           action_type: str | None = None) -> list[dict]:
    conditions = []
    params = {}
    if user_id:
        conditions.append("al.user_id = :user_id")
        params["user_id"] = user_id
    if action_type:
        conditions.append("al.action_type = :action_type")
        params["action_type"] = action_type
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = text(f"""
        SELECT al.timestamp, al.user_id,
               u.preferences->>'ab_group' AS ab_group,
               al.session_id, al.action_type, al.question_number, al.action_data
        FROM user_action_logs al
        JOIN users u ON u.id = al.user_id
        {where}
        ORDER BY al.timestamp DESC
    """)
    result = await db.execute(query, params)
    rows = [dict(r) for r in result.mappings().all()]
    for row in rows:
        row["action_data"] = _decode_json(row["action_data"])
    return rows


# --- KPIs ---

async def get_skill_mastery(db: AsyncSession, user_id: str) -> list[dict]:
    query = text("""
        SELECT skill_id, mastery_level, consecutive_errors, last_updated
        FROM skill_mastery
        WHERE user_id = :user_id
        ORDER BY last_updated DESC
    """)
    result = await db.execute(query, {"user_id": user_id})
    return [dict(r) for r in result.mappings().all()]


async def get_skill_mastery_trajectory(db: AsyncSession, user_id: str) -> list[dict]:
    """One dict per interaction step: {"interaction": i, skill_a: level, ...}.

    Step 0 is the starting state before any interaction, matching the
    original chart which always plotted an "Interaction 0" baseline point.
    """
    history = await get_raw_interaction_history(db, user_id)
    if not history:
        return []
    all_skills = sorted({row["skill"] for row in history if row["skill"] is not None})
    mastery_levels = {skill: settings.bkt_p_l0 for skill in all_skills}
    trajectory = []
    start_state = dict(mastery_levels)
    start_state["interaction"] = 0
    trajectory.append(start_state)
    for i, row in enumerate(history, start=1):
        skill = row["skill"]
        if row["user_answer"] is not None and skill in mastery_levels:
            mastery_levels[skill] = bkt_calculator.calculate_mastery_update(
                mastery_levels[skill], bool(row["is_correct"])
            )
        step = dict(mastery_levels)
        step["interaction"] = i
        trajectory.append(step)
    return trajectory


async def get_user_kpis(db: AsyncSession, user_id: str) -> dict:
    history = await get_raw_interaction_history(db, user_id)  # ascending by timestamp
    if not history:
        return {"overall_correctness": 0, "avg_attempts_to_correct": 0,
                "total_hints": 0, "avg_hint_rating": "N/A"}

    # Last attempt per question. history is timestamp-ascending, so the
    # last occurrence per question_id in iteration order is also the
    # latest attempt - mirrors the original groupby(...).idxmax() on a
    # timestamp-ascending frame.
    last_attempt_by_question: dict = {}
    for row in history:
        last_attempt_by_question[row["question_id"]] = row
    final_attempts = list(last_attempt_by_question.values())
    overall_correctness = (
        sum(1 for r in final_attempts if r["is_correct"]) / len(final_attempts)
        if final_attempts else 0
    )

    # Attempt number per question in chronological order, and the first
    # (lowest-numbered) attempt on which each question was answered
    # correctly. Mirrors groupby(...).cumcount() + 1 followed by
    # groupby(...).idxmin() on the correct-only subset.
    attempt_counters: dict = {}
    first_correct_attempt: dict = {}
    for row in history:
        qid = row["question_id"]
        attempt_counters[qid] = attempt_counters.get(qid, 0) + 1
        attempt_no = attempt_counters[qid]
        if row["is_correct"] and qid not in first_correct_attempt:
            first_correct_attempt[qid] = attempt_no
    avg_attempts = (
        sum(first_correct_attempt.values()) / len(first_correct_attempt)
        if first_correct_attempt else 0
    )

    total_hints = sum(1 for r in history if r["hint_shown"])
    ratings = [r["user_feedback_rating"] for r in history if r["user_feedback_rating"] is not None]
    avg_hint_rating = (sum(ratings) / len(ratings)) if ratings else "N/A"

    return {
        "overall_correctness": overall_correctness,
        "avg_attempts_to_correct": avg_attempts,
        "total_hints": total_hints,
        "avg_hint_rating": avg_hint_rating,
    }


# --- Admin writes ---

async def reset_user_progress(db: AsyncSession, user_id: str) -> None:
    await db.execute(text("DELETE FROM exam_sessions WHERE user_id = :user_id"), {"user_id": user_id})
    await db.execute(text("DELETE FROM user_action_logs WHERE user_id = :user_id"), {"user_id": user_id})
    await db.execute(text("DELETE FROM chat_logs WHERE user_id = :user_id"), {"user_id": user_id})
    await db.execute(text("DELETE FROM intervention_logs WHERE user_id = :user_id"), {"user_id": user_id})
    await db.execute(text("DELETE FROM interaction_logs WHERE user_id = :user_id"), {"user_id": user_id})
    await db.execute(text("DELETE FROM skill_mastery WHERE user_id = :user_id"), {"user_id": user_id})
    await db.execute(
        text("UPDATE participants SET status='unused', active_session_id=NULL WHERE token=:user_id"),
        {"user_id": user_id},
    )
    await db.commit()


async def delete_user(db: AsyncSession, user_id: str) -> None:
    await reset_user_progress(db, user_id)
    await db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
    await db.commit()


async def update_user_preferences(db: AsyncSession, user_id: str, prefs_update: dict) -> None:
    """Merges prefs_update into the user's existing preferences JSON column.

    Postgres jsonb CAST/|| syntax - not portable to SQLite. Preserved as-is
    on purpose; see ASSUMPTIONS.
    """
    await db.execute(
        text("UPDATE users SET preferences = CAST(preferences AS jsonb) || CAST(:prefs AS jsonb) WHERE id = :user_id"),
        {"user_id": user_id, "prefs": json.dumps(prefs_update)},
    )
    await db.commit()


async def reset_exam_timer(db: AsyncSession, user_id: str) -> None:
    """Resets exam_start_ms to NOW and clears submitted_at. Clears the
    participant lock so the student can re-enter."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        text("UPDATE exam_sessions SET exam_start_ms=:now_ms, submitted_at=NULL WHERE user_id=:user_id"),
        {"now_ms": now_ms, "user_id": user_id},
    )
    await db.execute(
        text("UPDATE participants SET status='unused', active_session_id=NULL, last_seen_at=NULL WHERE token=:user_id"),
        {"user_id": user_id},
    )
    await db.commit()


async def extend_exam_timer(db: AsyncSession, user_id: str, extra_minutes: int) -> None:
    extra_ms = extra_minutes * 60 * 1000
    await db.execute(
        text("UPDATE exam_sessions SET exam_duration_ms=exam_duration_ms+:extra WHERE user_id=:user_id"),
        {"extra": extra_ms, "user_id": user_id},
    )
    await db.commit()


async def clear_session_lock(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        text("UPDATE participants SET active_session_id=NULL, last_seen_at=NULL WHERE token=:user_id"),
        {"user_id": user_id},
    )
    await db.commit()


async def get_exam_session_info(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(
        text("SELECT exam_start_ms, exam_duration_ms, submitted_at FROM exam_sessions WHERE user_id=:user_id"),
        {"user_id": user_id},
    )
    row = result.mappings().first()
    if not row:
        return {}
    now_ms = int(time.time() * 1000)
    elapsed_ms = now_ms - row["exam_start_ms"]
    remaining_ms = max(0, row["exam_duration_ms"] - elapsed_ms)
    return {
        "exam_start_ms": row["exam_start_ms"],
        "exam_duration_ms": row["exam_duration_ms"],
        "remaining_ms": remaining_ms,
        "remaining_min": round(remaining_ms / 60000, 1),
        "submitted": row["submitted_at"] is not None,
    }


async def get_participant_info(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(
        text("SELECT status, active_session_id, last_seen_at FROM participants WHERE token=:user_id"),
        {"user_id": user_id},
    )
    row = result.mappings().first()
    if not row:
        return {}
    return {
        "status": row["status"],
        "active_session_id": row["active_session_id"],
        "last_seen_at": str(row["last_seen_at"]) if row["last_seen_at"] else None,
    }


# --- Bulk / exam-wide ops (merged from streamlit_app/admin_ops.py) ---

# Shared with frontend/e2e/fixtures/extend_all_timers.py, which is expected
# to import this constant instead of streamlit_app.admin_ops.
# EXTEND_ALL_TIMERS_SQL going forward - not yet updated to do so, see
# ASSUMPTIONS.
EXTEND_ALL_TIMERS_SQL = (
    "UPDATE exam_sessions SET exam_duration_ms = exam_duration_ms + :extra WHERE submitted_at IS NULL"
)


async def count_active_sessions(db: AsyncSession) -> int:
    """Number of exam sessions not yet submitted - the set a bulk timer
    extension would affect."""
    result = await db.execute(text("SELECT COUNT(*) FROM exam_sessions WHERE submitted_at IS NULL"))
    return result.scalar_one()


async def extend_all_exam_timers(db: AsyncSession, extra_minutes: int) -> int:
    """Adds extra_minutes to exam_duration_ms for every unsubmitted
    session. Returns the number of rows updated."""
    extra_ms = extra_minutes * 60 * 1000
    result = await db.execute(text(EXTEND_ALL_TIMERS_SQL), {"extra": extra_ms})
    await db.commit()
    return result.rowcount


async def get_llm_usage_last_24h(db: AsyncSession) -> dict:
    """Global and per-user LLM call counts in the rolling 24h window
    app/services/llm_quota.py caps against.

    Uses Postgres NOW() - INTERVAL syntax. Not portable to SQLite -
    preserved as-is on purpose; see ASSUMPTIONS.
    """
    global_count = (await db.execute(
        text("SELECT COUNT(*) FROM llm_usage_log WHERE created_at >= NOW() - INTERVAL '24 hours'")
    )).scalar_one()

    top_result = await db.execute(
        text(
            "SELECT user_id, COUNT(*) AS calls "
            "FROM llm_usage_log WHERE created_at >= NOW() - INTERVAL '24 hours' "
            "GROUP BY user_id ORDER BY calls DESC LIMIT 10"
        )
    )
    top_users = [dict(r) for r in top_result.mappings().all()]
    return {"global_count": int(global_count), "top_users": top_users}