# Contains the logic for the Intervention Controller; monitors BKT outputs, user logs, and decides on proactive hints (uses asyncio for async scheduling)
# app/services/intervention.py
from app.utils.config import settings
from app.utils.logger import logger

def check_intervention(
    user_id: str, 
    skill: str, 
    time_taken_ms: int | None,
    current_mastery: float,
    consecutive_errors: int
) -> bool:
    """Checks if intervention is needed based on time, mastery, and errors."""

    # 1. Check Dynamic Time Taken first to ensure time-based tests are reliable.
    if time_taken_ms is not None:
        base_limit = settings.intervention_time_limit_ms
        # This balanced formula scales the multiplier between 0.8 and 1.2
        mastery_multiplier = 0.8 + (current_mastery * 0.4)
        adjusted_time_limit = base_limit * mastery_multiplier
        
        logger.debug(f"Dynamic check for {user_id} on {skill}: Mastery={current_mastery:.2f}, Multiplier={mastery_multiplier:.2f}, Adjusted Time Limit={adjusted_time_limit:.0f}ms")

        if time_taken_ms > adjusted_time_limit:
            logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Time ({time_taken_ms}ms) > Adjusted Threshold ({adjusted_time_limit:.0f}ms)")
            return True

    # 2. Check Mastery Threshold (Immediate check for struggling users)
    if current_mastery < settings.intervention_mastery_threshold:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Mastery ({current_mastery:.3f}) < Threshold ({settings.intervention_mastery_threshold})")
        return True

    # 3. Check Consecutive Errors
    if consecutive_errors >= settings.intervention_max_consecutive_errors:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Errors ({consecutive_errors}) >= Threshold ({settings.intervention_max_consecutive_errors})")
        return True

    logger.debug(f"No intervention triggered for User: {user_id}, Skill: {skill}")
    return False
