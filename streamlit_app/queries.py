# streamlit_app/queries.py
import json
import time
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
import streamlit as st
from app.utils.config import settings


# --- BKT Logic Mirror ---
class BKTCalculator:
    def __init__(self, p_l0, p_t, p_g, p_s):
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
    p_s=settings.bkt_p_s
)


# Read queries are cached so a widget interaction (which re-runs the whole
# Streamlit script) doesn't re-issue every query. Kept short because the
# dashboard is watched live during an exam; every admin write below calls
# st.cache_data.clear() so an action's effect is never hidden by the cache.
CACHE_TTL_SECONDS = 10


# --- Cached Data Loading ---
@st.cache_data
def load_questions(path: str = settings.QUESTION_CSV_FILE_PATH):
    try:
        df = pd.read_csv(path)
        df['id'] = df['id'].astype(int)
        return df
    except FileNotFoundError:
        st.error(f"Question file not found at {path}.")
        return pd.DataFrame()


QUESTIONS_DF = load_questions()


# --- User Queries ---
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_all_user_ids(_db: Session) -> list:
    query = text("SELECT id FROM users ORDER BY created_at DESC")
    return [row[0] for row in _db.execute(query)]


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_all_users_summary(_db: Session) -> pd.DataFrame:
    """Returns all users with their A/B group, creation time, basic stats, and timer info.

    Each log table is aggregated to one row per user *before* being joined onto
    users. Joining interaction_logs and chat_logs onto the same user row directly
    produces a cartesian product (interactions x chats), which both inflates the
    non-DISTINCT SUMs and makes the query cost grow quadratically with activity.
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
    df = pd.read_sql(query, _db.connection())
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'])
        now_ms = int(time.time() * 1000)
        def _remaining_min(row):
            if pd.isna(row['exam_start_ms']) or pd.isna(row['exam_duration_ms']):
                return None
            elapsed = now_ms - int(row['exam_start_ms'])
            remaining = max(0, int(row['exam_duration_ms']) - elapsed)
            return remaining // 60000
        df['remaining_min'] = df.apply(_remaining_min, axis=1)
        df['submitted'] = df['submitted_at'].notna()
    return df


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_user_profile(_db: Session, user_id: str) -> dict:
    query = text("SELECT id, created_at, preferences, feedback_scores FROM users WHERE id = :user_id")
    result = _db.execute(query, {"user_id": user_id}).first()
    return dict(result._mapping) if result else {}


# --- Interaction Logs ---
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_raw_interaction_history(_db: Session, user_id: str) -> pd.DataFrame:
    query = text("""
        SELECT timestamp, question_id, skill, user_answer, is_correct,
               hint_shown, hint_style_used, hint_text, user_feedback_rating, bkt_change
        FROM interaction_logs
        WHERE user_id = :user_id
        ORDER BY timestamp ASC
    """)
    df = pd.read_sql(query, _db.connection(), params={"user_id": user_id})
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_interaction_history(_db: Session, user_id: str) -> pd.DataFrame:
    df = get_raw_interaction_history(_db, user_id)
    if not df.empty and not QUESTIONS_DF.empty:
        df['question_id'] = df['question_id'].astype(int)
        merged_df = pd.merge(
            df, QUESTIONS_DF[['id', 'question']],
            left_on='question_id', right_on='id', how='left'
        )
        cols = ['timestamp', 'question_id', 'question', 'user_answer', 'is_correct', 'skill',
                'hint_shown', 'hint_style_used', 'hint_text', 'user_feedback_rating', 'bkt_change']
        final_cols = [col for col in cols if col in merged_df.columns]
        return merged_df[final_cols].sort_values(by='timestamp', ascending=False)
    if not df.empty and 'question' not in df.columns:
        df['question'] = None
    return df.sort_values(by='timestamp', ascending=False) if not df.empty else df


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_all_interaction_logs(_db: Session, user_id: str | None = None) -> pd.DataFrame:
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
    df = pd.read_sql(query, _db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- Chat Logs ---
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_chat_logs(_db: Session, user_id: str | None = None) -> pd.DataFrame:
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
    df = pd.read_sql(query, _db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- Intervention Logs ---
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_intervention_logs(_db: Session, user_id: str | None = None) -> pd.DataFrame:
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
    df = pd.read_sql(query, _db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- Action Logs ---
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_action_logs(_db: Session, user_id: str | None = None,
                    action_type: str | None = None) -> pd.DataFrame:
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
    df = pd.read_sql(query, _db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- KPIs ---
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_skill_mastery(_db: Session, user_id: str) -> pd.DataFrame:
    query = text("""
        SELECT skill_id, mastery_level, consecutive_errors, last_updated
        FROM skill_mastery
        WHERE user_id = :user_id
        ORDER BY last_updated DESC
    """)
    return pd.read_sql(query, _db.connection(), params={"user_id": user_id})


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_skill_mastery_trajectory(_db: Session, user_id: str) -> pd.DataFrame:
    history_df = get_raw_interaction_history(_db, user_id)
    if history_df.empty:
        return pd.DataFrame()
    initial_mastery = settings.bkt_p_l0
    all_skills = history_df['skill'].unique()
    mastery_levels = {skill: initial_mastery for skill in all_skills}
    trajectory_data = []
    start_state = mastery_levels.copy()
    start_state['Interaction'] = 0
    trajectory_data.append(start_state)
    for i, (_, row) in enumerate(history_df.iterrows(), 1):
        skill = row['skill']
        if pd.notna(row['user_answer']):
            mastery_levels[skill] = bkt_calculator.calculate_mastery_update(
                mastery_levels[skill], row['is_correct']
            )
        step = mastery_levels.copy()
        step['Interaction'] = i
        trajectory_data.append(step)
    return pd.DataFrame(trajectory_data).set_index('Interaction')


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_user_kpis(_db: Session, user_id: str) -> dict:
    history_df = get_raw_interaction_history(_db, user_id)
    if history_df.empty:
        return {"overall_correctness": 0, "avg_attempts_to_correct": 0,
                "total_hints": 0, "avg_hint_rating": "N/A"}
    final_attempts = history_df.loc[history_df.groupby('question_id')['timestamp'].idxmax()]
    overall_correctness = final_attempts['is_correct'].mean() if not final_attempts.empty else 0
    history_df['attempt'] = history_df.groupby('question_id').cumcount() + 1
    correct_attempts = history_df[history_df['is_correct']]
    first_correct = correct_attempts.loc[correct_attempts.groupby('question_id')['attempt'].idxmin()]
    avg_attempts = first_correct['attempt'].mean() if not first_correct.empty else 0
    total_hints = int(history_df['hint_shown'].sum())
    rated = history_df['user_feedback_rating'].dropna()
    avg_hint_rating = rated.mean() if len(rated) > 0 else "N/A"
    return {
        "overall_correctness": overall_correctness,
        "avg_attempts_to_correct": avg_attempts,
        "total_hints": total_hints,
        "avg_hint_rating": avg_hint_rating,
    }


# --- Admin ---
def reset_user_progress(db: Session, user_id: str):
    db.execute(text("DELETE FROM exam_sessions WHERE user_id = :user_id"), {"user_id": user_id})
    db.execute(text("DELETE FROM user_action_logs WHERE user_id = :user_id"), {"user_id": user_id})
    db.execute(text("DELETE FROM chat_logs WHERE user_id = :user_id"), {"user_id": user_id})
    db.execute(text("DELETE FROM intervention_logs WHERE user_id = :user_id"), {"user_id": user_id})
    db.execute(text("DELETE FROM interaction_logs WHERE user_id = :user_id"), {"user_id": user_id})
    db.execute(text("DELETE FROM skill_mastery WHERE user_id = :user_id"), {"user_id": user_id})
    # Reset participant so they can re-enter as a fresh start
    db.execute(
        text("UPDATE participants SET status='unused', active_session_id=NULL WHERE token=:user_id"),
        {"user_id": user_id},
    )
    db.commit()
    st.cache_data.clear()


def delete_user(db: Session, user_id: str):
    reset_user_progress(db, user_id)
    db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
    db.commit()
    st.cache_data.clear()


def update_user_preferences(db: Session, user_id: str, prefs_update: dict):
    """Merges prefs_update into the user's existing preferences JSON column."""
    db.execute(
        text("UPDATE users SET preferences = CAST(preferences AS jsonb) || CAST(:prefs AS jsonb) WHERE id = :user_id"),
        {"user_id": user_id, "prefs": json.dumps(prefs_update)},
    )
    db.commit()
    st.cache_data.clear()


def reset_exam_timer(db: Session, user_id: str):
    """Resets exam_start_ms to NOW and clears submitted_at. Clears participant lock so student can re-enter."""
    now_ms = int(time.time() * 1000)
    db.execute(
        text("UPDATE exam_sessions SET exam_start_ms=:now_ms, submitted_at=NULL WHERE user_id=:user_id"),
        {"now_ms": now_ms, "user_id": user_id},
    )
    db.execute(
        text("UPDATE participants SET status='unused', active_session_id=NULL, last_seen_at=NULL WHERE token=:user_id"),
        {"user_id": user_id},
    )
    db.commit()
    st.cache_data.clear()


def extend_exam_timer(db: Session, user_id: str, extra_minutes: int):
    """Adds extra_minutes to the user's remaining exam time."""
    extra_ms = extra_minutes * 60 * 1000
    db.execute(
        text("UPDATE exam_sessions SET exam_duration_ms=exam_duration_ms+:extra WHERE user_id=:user_id"),
        {"extra": extra_ms, "user_id": user_id},
    )
    db.commit()
    st.cache_data.clear()


def clear_session_lock(db: Session, user_id: str):
    """Clears active_session_id and last_seen_at so the student can re-enter from any device."""
    db.execute(
        text("UPDATE participants SET active_session_id=NULL, last_seen_at=NULL WHERE token=:user_id"),
        {"user_id": user_id},
    )
    db.commit()
    st.cache_data.clear()


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_exam_session_info(_db: Session, user_id: str) -> dict:
    """Returns current timer info for a user."""
    result = _db.execute(
        text("SELECT exam_start_ms, exam_duration_ms, submitted_at FROM exam_sessions WHERE user_id=:user_id"),
        {"user_id": user_id},
    ).first()
    if not result:
        return {}
    now_ms = int(time.time() * 1000)
    elapsed_ms = now_ms - result.exam_start_ms
    remaining_ms = max(0, result.exam_duration_ms - elapsed_ms)
    return {
        "exam_start_ms": result.exam_start_ms,
        "exam_duration_ms": result.exam_duration_ms,
        "remaining_ms": remaining_ms,
        "remaining_min": round(remaining_ms / 60000, 1),
        "submitted": result.submitted_at is not None,
    }


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_participant_info(_db: Session, user_id: str) -> dict:
    """Returns participant lock status."""
    result = _db.execute(
        text("SELECT status, active_session_id, last_seen_at FROM participants WHERE token=:user_id"),
        {"user_id": user_id},
    ).first()
    if not result:
        return {}
    return {
        "status": result.status,
        "active_session_id": result.active_session_id,
        "last_seen_at": str(result.last_seen_at) if result.last_seen_at else None,
    }
