# app/endpoints/users.py
from fastapi import APIRouter, HTTPException
from typing import Dict
from pydantic import BaseModel # Make sure BaseModel is imported
from collections import deque # Import deque

# Import necessary services and functions
from app.services.question_service import question_service
# --- CORRECTED IMPORTS ---
from app.state_manager import get_bkt_mastery, get_user_state
# --- END CORRECTED IMPORTS ---
from app.utils.config import settings
from app.utils.logger import logger

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# --- BasicUserState Model (ensure it's defined) ---
class BasicUserState(BaseModel):
    bkt: Dict[str, float]
    log: list # Deque gets converted to list for JSON serialization
    consecutive_errors: Dict[str, int]
    # Add other state components here if needed (e.g., preferences)
# --- End BasicUserState Model ---

@router.get("/{user_id}/bkt", response_model=Dict[str, float])
async def get_user_bkt_state(user_id: str):
    """
    Retrieves the current Bayesian Knowledge Tracing (BKT) mastery state
    for a given user across all known skills.
    Returns the default initial probability (p_l0) for skills the user
    has not interacted with yet.
    """
    logger.debug(f"Fetching BKT state for user_id: {user_id}")
    all_skills = question_service.get_all_skills()
    if not all_skills:
        logger.warning("No skills loaded from question service. Cannot determine BKT state.")
        return {}

    bkt_state: Dict[str, float] = {}
    for skill in all_skills:
        # get_bkt_mastery handles fetching from state or returning default
        mastery = get_bkt_mastery(user_id, skill, settings.bkt_p_l0)
        bkt_state[skill] = mastery

    logger.debug(f"Returning BKT state for user {user_id}: {bkt_state}")
    return bkt_state


@router.get("/{user_id}/state", response_model=BasicUserState)
async def get_user_full_state(user_id: str):
    """
    Retrieves a summary of the user's current state, including BKT mastery,
    interaction log (as list), and consecutive errors per skill.
    """
    logger.debug(f"Fetching full state for user_id: {user_id}")

    # Fetch BKT state (reuse the logic or call the function if refactored)
    all_skills = question_service.get_all_skills()
    bkt_state: Dict[str, float] = {}
    if all_skills:
        for skill in all_skills:
            mastery = get_bkt_mastery(user_id, skill, settings.bkt_p_l0)
            bkt_state[skill] = mastery

    # --- CORRECTED STATE ACCESS ---
    # Fetch the entire user state object using the available function
    user_state = get_user_state(user_id) # Get the state dict/object for the user

    # Safely access log and errors from the state object using dictionary keys
    user_log_deque = user_state.get('log', deque()) # Get log deque, default to empty deque
    consecutive_errors = user_state.get('consecutive_errors', {}) # Get errors dict, default to empty dict
    # --- END CORRECTED STATE ACCESS ---

    # Convert deque to list for JSON compatibility
    log_list = list(user_log_deque)

    full_state = {
        "bkt": bkt_state, # Include the BKT state we fetched earlier
        "log": log_list,
        "consecutive_errors": consecutive_errors
    }

    logger.debug(f"Returning full state for user {user_id}: {full_state}")
    # Ensure the returned dictionary matches the BasicUserState model
    return BasicUserState(**full_state) # Validate against the model before returning