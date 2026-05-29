# Contains the logic for the Intervention Controller; monitors BKT outputs, user logs, and decides on proactive hints (uses asyncio for async scheduling)
# app/services/intervention.py
from app.utils.config import settings
from app.utils.logger import logger

def check_intervention(
    user_id: str,
    skill: str,
    time_taken_ms: int | None,
    current_mastery: float,
    consecutive_errors: int,
    consecutive_skips: int
) -> str | None:
    """Checks if intervention is needed. Returns the trigger reason string, or None if no intervention."""

    # 1. Consecutive errors — most specific behavioral signal
    if consecutive_errors >= settings.intervention_max_consecutive_errors:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Errors ({consecutive_errors}) >= Threshold ({settings.intervention_max_consecutive_errors})")
        return "consecutive_errors"

    # 2. Consecutive skips — specific behavioral signal
    if consecutive_skips >= settings.intervention_max_consecutive_skips:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Skips ({consecutive_skips}) >= Threshold ({settings.intervention_max_consecutive_skips})")
        return "consecutive_skips"

    # 3. Low mastery — knowledge-based signal
    if current_mastery < settings.intervention_mastery_threshold:
        logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Mastery ({current_mastery:.3f}) < Threshold ({settings.intervention_mastery_threshold})")
        return "low_mastery"

    # 4. Time spent — fallback, only fires when no behavioral signal present
    if time_taken_ms is not None:
        base_limit = settings.intervention_time_limit_ms
        mastery_multiplier = 0.8 + (current_mastery * 0.4)
        adjusted_time_limit = base_limit * mastery_multiplier

        logger.debug(f"Dynamic check for {user_id} on {skill}: Mastery={current_mastery:.2f}, Multiplier={mastery_multiplier:.2f}, Adjusted Time Limit={adjusted_time_limit:.0f}ms")

        if time_taken_ms > adjusted_time_limit:
            logger.info(f"Intervention Triggered (User: {user_id}, Skill: {skill}): Time ({time_taken_ms}ms) > Adjusted Threshold ({adjusted_time_limit:.0f}ms)")
            return "time_spent"

    logger.debug(f"No intervention triggered for User: {user_id}, Skill: {skill}")
    return None
