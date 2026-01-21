# streamlit_app/queries.py
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
import streamlit as st
from app.utils.config import settings

# --- BKT Logic Mirror ---
# This is a synchronous, non-database version of the BKTService logic
# to allow for historical trajectory recalculation without async calls.

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
        if prob_evidence == 0: return prior_ln
        
        posterior = (prob_evidence_given_ln * prior_ln) / prob_evidence
        return max(0.0, min(1.0, posterior))

    def calculate_mastery_update(self, prior_ln_minus_1: float, is_correct: bool) -> float:
        posterior_ln_minus_1 = self._calculate_posterior(prior_ln_minus_1, is_correct)
        new_ln = posterior_ln_minus_1 + (1.0 - posterior_ln_minus_1) * self.p_t
        return max(0.0, min(1.0, new_ln))

# Instantiate the calculator with settings from the config file, which loads .env
bkt_calculator = BKTCalculator(
    p_l0=settings.bkt_p_l0,
    p_t=settings.bkt_p_t,
    p_g=settings.bkt_p_g,
    p_s=settings.bkt_p_s
)

# --- Cached Data Loading ---
@st.cache_data
def load_questions(path: str = settings.QUESTION_CSV_FILE_PATH):
    """Loads the question data into a cached DataFrame."""
    try:
        df = pd.read_csv(path)
        df['id'] = df['id'].astype(int)
        return df
    except FileNotFoundError:
        st.error(f"Question file not found at {path}. Please ensure the file exists.")
        return pd.DataFrame()

QUESTIONS_DF = load_questions()

# --- Query Functions ---
def get_all_user_ids(db: Session) -> list:
    """Fetches a list of all unique user IDs."""
    query = text("SELECT id FROM users ORDER BY created_at DESC")
    result = db.execute(query)
    return [row[0] for row in result]

def get_user_profile(db: Session, user_id: str) -> dict:
    """Fetches the raw profile data for a single user."""
    query = text("SELECT id, created_at, preferences, feedback_scores FROM users WHERE id = :user_id")
    result = db.execute(query, {"user_id": user_id}).first()
    return dict(result._mapping) if result else {}

def get_skill_mastery(db: Session, user_id: str) -> pd.DataFrame:
    """Fetches the final skill mastery records for a user."""
    query = text("""
        SELECT skill_id, mastery_level, consecutive_errors, last_updated 
        FROM skill_mastery 
        WHERE user_id = :user_id 
        ORDER BY last_updated DESC
    """)
    return pd.read_sql(query, db.connection(), params={"user_id": user_id})

def get_raw_interaction_history(db: Session, user_id: str) -> pd.DataFrame:
    """Fetches the raw interaction history for a user, ordered chronologically."""
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
    """Fetches and enriches the interaction history for display, ordered newest first."""
    df = get_raw_interaction_history(db, user_id)
    
    if not df.empty and not QUESTIONS_DF.empty:
        df['question_id'] = df['question_id'].astype(int)
        merged_df = pd.merge(
            df, 
            QUESTIONS_DF[['id', 'question']], 
            left_on='question_id', 
            right_on='id', 
            how='left'
        )
        cols = ['timestamp', 'question_id', 'question', 'user_answer', 'is_correct', 'skill', 
                'hint_shown', 'hint_style_used', 'hint_text', 'user_feedback_rating', 'bkt_change']
        final_cols = [col for col in cols if col in merged_df.columns]
        return merged_df[final_cols].sort_values(by='timestamp', ascending=False)
    
    return df.sort_values(by='timestamp', ascending=False) if not df.empty else df


def get_skill_mastery_trajectory(db: Session, user_id: str) -> pd.DataFrame:
    """
    Calculates the true BKT trajectory by re-simulating the mastery updates
    based on the user's chronological interaction history. This version correctly
    identifies skipped questions.
    """
    history_df = get_raw_interaction_history(db, user_id)
    if history_df.empty:
        return pd.DataFrame()

    initial_mastery = settings.bkt_p_l0
    all_skills = history_df['skill'].unique()
    
    mastery_levels = {skill: initial_mastery for skill in all_skills}
    trajectory_data = []

    # Add the starting state at Interaction 0
    start_state = mastery_levels.copy()
    start_state['Interaction'] = 0
    trajectory_data.append(start_state)

    interaction_counter = 1
    for _, row in history_df.iterrows():
        skill = row['skill']
        is_correct = row['is_correct']
        user_answer = row['user_answer']
        
        prior_mastery = mastery_levels[skill]
        
        # THE FINAL, CORRECT FIX: A BKT update only happens if the user provided an answer.
        # A blank/null user_answer indicates a skip, which does not affect BKT.
        if pd.notna(user_answer):
            new_mastery = bkt_calculator.calculate_mastery_update(prior_mastery, is_correct)
            mastery_levels[skill] = new_mastery
        # If user_answer is null, it was a skip, and mastery_levels remains unchanged.
        
        # Record the complete state of all skills after this interaction
        step_data = mastery_levels.copy()
        step_data['Interaction'] = interaction_counter
        trajectory_data.append(step_data)
        interaction_counter += 1

    if not trajectory_data:
        return pd.DataFrame()

    # Convert the list of snapshots into a DataFrame
    trajectory_df = pd.DataFrame(trajectory_data).set_index('Interaction')
    
    return trajectory_df


def get_user_kpis(db: Session, user_id: str) -> dict:
    """Calculates key performance indicators for a single user."""
    history_df = get_raw_interaction_history(db, user_id)
    if history_df.empty:
        return {
            "overall_correctness": 0,
            "avg_attempts_to_correct": 0,
            "total_hints": 0,
            "avg_hint_rating": "N/A"
        }

    final_attempts = history_df.loc[history_df.groupby('question_id')['timestamp'].idxmax()]
    overall_correctness = final_attempts['is_correct'].mean() if not final_attempts.empty else 0

    history_df['attempt'] = history_df.groupby('question_id').cumcount() + 1
    correct_attempts = history_df[history_df['is_correct']]
    first_correct_attempts = correct_attempts.loc[correct_attempts.groupby('question_id')['attempt'].idxmin()]
    avg_attempts = first_correct_attempts['attempt'].mean() if not first_correct_attempts.empty else 0

    total_hints = history_df['hint_shown'].sum()
    avg_hint_rating = history_df['user_feedback_rating'].dropna().mean() if total_hints > 0 and not history_df['user_feedback_rating'].dropna().empty else "N/A"

    return {
        "overall_correctness": overall_correctness,
        "avg_attempts_to_correct": avg_attempts,
        "total_hints": int(total_hints),
        "avg_hint_rating": avg_hint_rating
    }


def reset_user_progress(db: Session, user_id: str):
    """Deletes a user's interaction and mastery data."""
    db.execute(text("DELETE FROM interaction_logs WHERE user_id = :user_id"), {"user_id": user_id})
    db.execute(text("DELETE FROM skill_mastery WHERE user_id = :user_id"), {"user_id": user_id})
    db.commit()

def delete_user(db: Session, user_id: str):
    """Deletes a user and all their data."""
    reset_user_progress(db, user_id) 
    db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
    db.commit()