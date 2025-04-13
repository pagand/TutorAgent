# app/state_manager.py
from collections import defaultdict, deque
from typing import Dict, List, DefaultDict, Deque
from app.models.log import LogEntry
from app.utils.logger import logger
from datetime import datetime



# In-memory store for POC. Replace with DB for persistence.
# Structure: user_id -> { "bkt": {skill: mastery_prob}, "log": deque([LogEntry]), "consecutive_errors": {skill: count} }
user_states: Dict[str, Dict] = defaultdict(lambda: {
    "bkt": defaultdict(float), # Stores P(L_n) for each skill
    "log": deque(maxlen=100), # Store last N log entries per user
    "consecutive_errors": defaultdict(int)
})

MAX_LOG_SIZE = 100 # Can be configured

def get_user_state(user_id: str) -> Dict:
    """Initializes state for a user if they don't exist."""
    if user_id not in user_states:
         logger.info(f"Initializing state for new user: {user_id}")
         # The defaultdict handles creation, just access it
         _ = user_states[user_id]
    return user_states[user_id]


def add_log_entry(user_id: str, log_data: dict):
    """Adds a log entry and updates consecutive error counts."""
    state = get_user_state(user_id)
    try:
        log_entry = LogEntry(timestamp=datetime.now(), user_id=user_id, **log_data)
        state["log"].append(log_entry) # Append to deque

        # Update consecutive errors if the action was 'answered'
        if log_entry.action == "answered" and log_entry.skill is not None:
            skill = log_entry.skill
            if log_entry.is_correct:
                state["consecutive_errors"][skill] = 0 # Reset on correct
            else:
                state["consecutive_errors"][skill] += 1 # Increment on incorrect
            logger.debug(f"User {user_id}, Skill {skill}: Consecutive errors = {state['consecutive_errors'][skill]}")
            # NEED TO BE DELETED (JUST FOR DEBUGGING)
            logger.info(f"Full BKT state for user {user_id}: {user_states[user_id]['bkt']}")


    except Exception as e:
        logger.exception(f"Failed to add log entry for user {user_id}: {e}")

def get_last_n_logs(user_id: str, n: int = 10) -> List[LogEntry]:
    """Gets the last N log entries for a user."""
    state = get_user_state(user_id)
    return list(state["log"])[-n:]

def get_consecutive_errors(user_id: str, skill: str) -> int:
    """Gets the current consecutive error count for a skill."""
    state = get_user_state(user_id)
    return state["consecutive_errors"].get(skill, 0)

# --- BKT State Management (could be separate functions or part of BKT service) ---

def get_bkt_mastery(user_id: str, skill: str, default_mastery: float) -> float:
    """Gets BKT mastery for a skill, returning default if not set."""
    state = get_user_state(user_id)
    return state["bkt"].get(skill, default_mastery)

def update_bkt_mastery(user_id: str, skill: str, new_mastery: float):
    """Updates the stored BKT mastery for a skill."""
    state = get_user_state(user_id)
    state["bkt"][skill] = new_mastery
    logger.debug(f"User {user_id}, Skill {skill}: Updated BKT mastery = {new_mastery:.4f}")