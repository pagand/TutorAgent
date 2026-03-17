# streamlit_app/queries.py
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
def get_all_user_ids(db: Session) -> list:
    query = text("SELECT id FROM users ORDER BY created_at DESC")
    return [row[0] for row in db.execute(query)]


def get_all_users_summary(db: Session) -> pd.DataFrame:
    """Returns all users with their A/B group, creation time, and basic stats."""
    query = text("""
        SELECT
            u.id AS user_id,
            u.created_at,
            u.preferences->>'ab_group' AS ab_group,
            u.preferences->>'hint_style_preference' AS hint_style_pref,
            u.preferences->>'intervention_preference' AS intervention_pref,
            COUNT(DISTINCT il.id) AS total_interactions,
            SUM(CASE WHEN il.is_correct THEN 1 ELSE 0 END) AS correct_answers,
            SUM(CASE WHEN il.hint_shown THEN 1 ELSE 0 END) AS hints_used,
            COUNT(DISTINCT cl.id) AS chat_messages
        FROM users u
        LEFT JOIN interaction_logs il ON il.user_id = u.id
        LEFT JOIN chat_logs cl ON cl.user_id = u.id
        GROUP BY u.id, u.created_at
        ORDER BY u.created_at DESC
    """)
    df = pd.read_sql(query, db.connection())
    if not df.empty:
        df['created_at'] = pd.to_datetime(df['created_at'])
    return df


def get_user_profile(db: Session, user_id: str) -> dict:
    query = text("SELECT id, created_at, preferences, feedback_scores FROM users WHERE id = :user_id")
    result = db.execute(query, {"user_id": user_id}).first()
    return dict(result._mapping) if result else {}


# --- Interaction Logs ---
def get_raw_interaction_history(db: Session, user_id: str) -> pd.DataFrame:
    query = text("""
        SELECT timestamp, question_id, skill, user_answer, is_correct,
               hint_shown, hint_style_used, hint_text, user_feedback_rating, bkt_change
        FROM interaction_logs
        WHERE user_id = :user_id
        ORDER BY timestamp ASC
    """)
    df = pd.read_sql(query, db.connection(), params={"user_id": user_id})
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def get_interaction_history(db: Session, user_id: str) -> pd.DataFrame:
    df = get_raw_interaction_history(db, user_id)
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


def get_all_interaction_logs(db: Session, user_id: str | None = None) -> pd.DataFrame:
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
    df = pd.read_sql(query, db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- Chat Logs ---
def get_chat_logs(db: Session, user_id: str | None = None) -> pd.DataFrame:
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
    df = pd.read_sql(query, db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- Intervention Logs ---
def get_intervention_logs(db: Session, user_id: str | None = None) -> pd.DataFrame:
    where = "WHERE il.user_id = :user_id" if user_id else ""
    params = {"user_id": user_id} if user_id else {}
    query = text(f"""
        SELECT il.timestamp, il.user_id,
               u.preferences->>'ab_group' AS ab_group,
               il.session_id, il.question_number, il.time_on_question_ms,
               il.mastery_at_trigger, il.accepted
        FROM intervention_logs il
        JOIN users u ON u.id = il.user_id
        {where}
        ORDER BY il.timestamp DESC
    """)
    df = pd.read_sql(query, db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- Action Logs ---
def get_action_logs(db: Session, user_id: str | None = None,
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
    df = pd.read_sql(query, db.connection(), params=params)
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# --- KPIs ---
def get_skill_mastery(db: Session, user_id: str) -> pd.DataFrame:
    query = text("""
        SELECT skill_id, mastery_level, consecutive_errors, last_updated
        FROM skill_mastery
        WHERE user_id = :user_id
        ORDER BY last_updated DESC
    """)
    return pd.read_sql(query, db.connection(), params={"user_id": user_id})


def get_skill_mastery_trajectory(db: Session, user_id: str) -> pd.DataFrame:
    history_df = get_raw_interaction_history(db, user_id)
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


def get_user_kpis(db: Session, user_id: str) -> dict:
    history_df = get_raw_interaction_history(db, user_id)
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
    db.commit()


def delete_user(db: Session, user_id: str):
    reset_user_progress(db, user_id)
    db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
    db.commit()
