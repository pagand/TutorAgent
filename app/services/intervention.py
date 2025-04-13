# Contains the logic for the Intervention Controller; monitors BKT outputs, user logs, and decides on proactive hints (uses asyncio for async scheduling)
# app/services/intervention.py
from app.utils.config import settings
from app.utils.logger import logger
from app.state_manager import get_bkt_mastery, get_consecutive_errors

def check_intervention(user_id: str, skill: str, time_taken_ms: int | None) -> bool:
    """Checks if intervention is needed based on mastery, errors, and time."""

    # 1. Check Mastery Threshold
    current_mastery = get_bkt_mastery(user_id, skill, settings.bkt_p_l0)
    if current_mastery < settings.intervention_mastery_threshold:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Mastery ({current_mastery:.3f}) < Threshold ({settings.intervention_mastery_threshold})")
        return True

    # 2. Check Consecutive Errors
    consecutive_errors = get_consecutive_errors(user_id, skill)
    if consecutive_errors >= settings.intervention_max_consecutive_errors:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Errors ({consecutive_errors}) >= Threshold ({settings.intervention_max_consecutive_errors})")
        return True

    # 3. Check Time Taken (if provided)
    if time_taken_ms is not None and time_taken_ms > settings.intervention_time_limit_ms:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Time ({time_taken_ms}ms) > Threshold ({settings.intervention_time_limit_ms}ms)")
        return True

    logger.debug(f"No intervention triggered for User: {user_id}, Skill: {skill}")
    return False