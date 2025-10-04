# streamlit_app/queries.py
import pandas as pd
from sqlalchemy.orm import Session
import sys
import os

# Add project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.models.user import User, SkillMastery, InteractionLog
from app.services.question_service import question_service

# Load questions once to map question IDs to text
# This needs to be called by the main app at startup
def load_questions():
    if not question_service.questions:
        question_service.load_questions()

def get_question_text(question_id: int) -> str:
    """Gets the question text for a given ID."""
    question = question_service.get_question_by_id(question_id)
    return question.question if question else "Question not found"

def get_all_user_ids(db: Session) -> list[str]:
    """Fetches a list of all user IDs from the database."""
    users = db.query(User.id).order_by(User.created_at.desc()).all()
    return [user.id for user in users]

def get_user_profile(db: Session, user_id: str) -> dict:
    """Fetches a user's core profile data."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {}
    # Convert to a JSON-serializable format
    return {
        "User ID": user.id,
        "Created At": user.created_at.isoformat(),
        "Preferences": user.preferences,
        "Feedback Scores": user.feedback_scores,
    }

def get_skill_mastery(db: Session, user_id: str) -> pd.DataFrame:
    """Fetches a user's skill mastery as a Pandas DataFrame."""
    mastery_records = db.query(SkillMastery).filter(SkillMastery.user_id == user_id).all()
    if not mastery_records:
        return pd.DataFrame(columns=["Skill", "Mastery Level", "Consecutive Errors", "Last Updated"])
    
    data = {
        "Skill": [record.skill_id for record in mastery_records],
        "Mastery Level": [f"{record.mastery_level:.2%}" for record in mastery_records],
        "Consecutive Errors": [record.consecutive_errors for record in mastery_records],
        "Last Updated": [record.last_updated.strftime('%Y-%m-%d %H:%M:%S') for record in mastery_records],
    }
    return pd.DataFrame(data)

def get_interaction_history(db: Session, user_id: str) -> pd.DataFrame:
    """Fetches a user's interaction history as a Pandas DataFrame."""
    logs = db.query(InteractionLog).filter(InteractionLog.user_id == user_id).order_by(InteractionLog.timestamp.desc()).all()
    if not logs:
        return pd.DataFrame(columns=["Timestamp", "Question ID", "Question", "User Answer", "Correct?", "Hint Shown?", "Hint Style", "Hint Text", "Feedback Rating", "BKT Change"])
        
    data = {
        "Timestamp": [log.timestamp.strftime('%Y-%m-%d %H:%M:%S') for log in logs],
        "Question ID": [log.question_id for log in logs],
        "Question": [get_question_text(log.question_id) for log in logs],
        "User Answer": [], # Will be populated below
        "Correct?": [log.is_correct for log in logs],
        "Hint Shown?": [log.hint_shown for log in logs],
        "Hint Style": [log.hint_style_used for log in logs],
        "Hint Text": [log.hint_text for log in logs], # <-- ADDED
        "Feedback Rating": [log.user_feedback_rating for log in logs],
        "BKT Change": [f"{log.bkt_change:.4f}" if log.bkt_change is not None else None for log in logs],
    }

    # --- NEW: Translate MC answer indexes to full text ---
    answer_texts = []
    for log in logs:
        question = question_service.get_question_by_id(log.question_id)
        answer_text = log.user_answer
        if question and question.question_type == 'multiple_choice':
            try:
                answer_index = int(log.user_answer) - 1
                if 0 <= answer_index < len(question.options):
                    answer_text = question.options[answer_index]
            except (ValueError, TypeError):
                pass # Keep the raw answer if it's not a valid index
        answer_texts.append(answer_text)
    
    data["User Answer"] = answer_texts
    # --- END NEW ---

    return pd.DataFrame(data)

def reset_user_progress(db: Session, user_id: str):
    """Deletes a user's interaction logs and skill mastery records."""
    db.query(InteractionLog).filter(InteractionLog.user_id == user_id).delete(synchronize_session=False)
    db.query(SkillMastery).filter(SkillMastery.user_id == user_id).delete(synchronize_session=False)
    db.commit()

def delete_user(db: Session, user_id: str):
    """Deletes a user and all their associated data."""
    # Must delete dependent records first due to foreign key constraints
    db.query(InteractionLog).filter(InteractionLog.user_id == user_id).delete(synchronize_session=False)
    db.query(SkillMastery).filter(SkillMastery.user_id == user_id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()
