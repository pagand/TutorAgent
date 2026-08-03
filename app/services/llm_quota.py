# app/services/llm_quota.py
# In-app LLM spend cap (Stage 4.5). nginx's rate limit is keyed per source
# IP and cannot see user_id, so it cannot bound cost per account or
# globally - see PRELAUNCH_CHECKLIST.md section 0 for the $/call arithmetic
# that sizes the two ceilings below. A rolling 24h window (not a UTC-day
# bucket) is used so there is no midnight boundary to reset against.
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import LlmUsageLog
from app.utils.config import settings
from app.utils.logger import logger

WINDOW = timedelta(hours=24)

PER_USER_DETAIL = "You've reached the maximum number of AI requests for today. Please continue without hints/chat, or contact your instructor."
GLOBAL_DETAIL = "The AI tutor is temporarily unavailable due to high demand. Please try again shortly."


async def reserve_llm_call(db: AsyncSession, user_id: str, endpoint: str) -> None:
    """Raises 429 if either the per-user or the global rolling-24h call cap
    is already reached; otherwise records this call and returns.

    Called BEFORE the LLM call itself (hints.py, chat.py), so a call that
    then errors out on the Gemini side still counts - it can still bill.
    Commits as part of the caller's existing transaction (both call sites
    already commit immediately after, to release the DB connection before
    the slow LLM call).
    """
    since = datetime.utcnow() - WINDOW

    global_count = await db.scalar(
        select(func.count()).select_from(LlmUsageLog).where(LlmUsageLog.created_at >= since)
    )
    if global_count >= settings.llm_max_calls_per_day:
        logger.error(
            f"LLM global daily cap reached: {global_count}/{settings.llm_max_calls_per_day} calls in the last 24h."
        )
        raise HTTPException(status_code=429, detail=GLOBAL_DETAIL)

    user_count = await db.scalar(
        select(func.count())
        .select_from(LlmUsageLog)
        .where(LlmUsageLog.user_id == user_id, LlmUsageLog.created_at >= since)
    )
    if user_count >= settings.llm_max_calls_per_user_per_day:
        logger.warning(
            f"LLM per-user daily cap reached for '{user_id}': "
            f"{user_count}/{settings.llm_max_calls_per_user_per_day} calls in the last 24h."
        )
        raise HTTPException(status_code=429, detail=PER_USER_DETAIL)

    db.add(LlmUsageLog(user_id=user_id, endpoint=endpoint))
