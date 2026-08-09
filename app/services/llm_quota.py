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

from app.models.user import AdminSetting, LlmUsageLog
from app.utils.config import settings
from app.utils.logger import logger

WINDOW = timedelta(hours=24)

PER_USER_DETAIL = "You've reached the maximum number of AI requests for today. Please continue without hints/chat, or contact your instructor."
GLOBAL_DETAIL = "The AI tutor is temporarily unavailable due to high demand. Please try again shortly."

# admin_settings keys. An absent key means "no override" and the value from
# settings (i.e. .env) applies, so the caps behave exactly as before until an
# admin actually raises one from the Exam tab.
CAP_GLOBAL_KEY = "llm_max_calls_per_day"
CAP_USER_KEY = "llm_max_calls_per_user_per_day"


async def get_cap_overrides(db: AsyncSession) -> dict[str, int]:
    """Admin-set cap overrides, empty when none are set.

    A malformed value is ignored with a warning rather than raised: this runs on
    the hint and chat path, and a bad row in a settings table must never be able
    to take the tutor down.
    """
    result = await db.execute(
        select(AdminSetting).where(AdminSetting.key.in_([CAP_GLOBAL_KEY, CAP_USER_KEY]))
    )
    overrides: dict[str, int] = {}
    for row in result.scalars().all():
        try:
            overrides[row.key] = int(row.value)
        except (TypeError, ValueError):
            logger.warning(f"Ignoring non-integer admin_settings override for '{row.key}': {row.value!r}")
    return overrides


async def get_effective_caps(db: AsyncSession) -> tuple[int, int]:
    """(global cap, per-user cap) with any admin override applied."""
    overrides = await get_cap_overrides(db)
    return (
        overrides.get(CAP_GLOBAL_KEY, settings.llm_max_calls_per_day),
        overrides.get(CAP_USER_KEY, settings.llm_max_calls_per_user_per_day),
    )


async def set_cap_override(db: AsyncSession, key: str, value: int | None) -> None:
    """Set or clear one cap override. `None` clears it, restoring the .env value."""
    existing = await db.get(AdminSetting, key)
    if value is None:
        if existing is not None:
            await db.delete(existing)
        return
    if existing is None:
        db.add(AdminSetting(key=key, value=str(value)))
    else:
        existing.value = str(value)
        existing.updated_at = datetime.utcnow()


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

    # One extra single-row-keyed SELECT on a table holding at most two rows,
    # alongside the two COUNTs already here. The alternative - raising a cap by
    # editing .env and restarting api mid-exam - is the thing this replaces.
    global_cap, user_cap = await get_effective_caps(db)

    global_count = await db.scalar(
        select(func.count()).select_from(LlmUsageLog).where(LlmUsageLog.created_at >= since)
    )
    if global_count >= global_cap:
        logger.error(
            f"LLM global daily cap reached: {global_count}/{global_cap} calls in the last 24h."
        )
        raise HTTPException(status_code=429, detail=GLOBAL_DETAIL)

    user_count = await db.scalar(
        select(func.count())
        .select_from(LlmUsageLog)
        .where(LlmUsageLog.user_id == user_id, LlmUsageLog.created_at >= since)
    )
    if user_count >= user_cap:
        logger.warning(
            f"LLM per-user daily cap reached for '{user_id}': "
            f"{user_count}/{user_cap} calls in the last 24h."
        )
        raise HTTPException(status_code=429, detail=PER_USER_DETAIL)

    db.add(LlmUsageLog(user_id=user_id, endpoint=endpoint))
