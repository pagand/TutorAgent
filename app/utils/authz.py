# app/utils/authz.py
# Row-level access control for the student-facing API.
#
# The exam-clock lock (Participant.active_session_id), established by
# POST /session/start and refreshed by the 25s heartbeat, is the only
# device-binding credential in the system. Every endpoint that acts on
# behalf of a specific user_id must confirm the caller holds that lock
# before touching that user's data - otherwise the participant token
# (the sole identifier) is enough on its own to read or mutate any
# student's exam as any other student.
#
# Participant-less user_ids (ad-hoc dev/test identities with no manifest
# entry) are exempt from the device-lock check ONLY when
# settings.require_participant_token is off (tests, ad-hoc local dev).
# In production (the default) a user_id with no Participant row is rejected
# outright - see PRELAUNCH_CHECKLIST.md section 0/Stage 4.5: this exemption,
# unconditional before Stage 4.5, was the front door that let anyone with no
# token at all create an account and use the API as an unmetered LLM proxy.
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Participant
from app.utils.config import settings

FORBIDDEN_DETAIL = "This exam token is not active on this device."
NO_PARTICIPANT_DETAIL = "Invalid exam token."


async def verify_session_owner(
    db: AsyncSession,
    user_id: str,
    session_id: str | None,
    *,
    allow_if_completed: bool = False,
) -> None:
    """Raises 403 unless session_id matches the participant's active device lock.

    When user_id has no Participant row: rejected with 403 if
    settings.require_participant_token is on (the production default), no-op
    (ad-hoc/dev/test identity) if it's off.
    When allow_if_completed is True, a participant whose exam is already
    completed is exempt too - used for read endpoints (profile, results)
    that legitimately need to work from a different device after the exam
    is over, e.g. a student checking their results on their phone.
    """
    result = await db.execute(select(Participant).filter_by(token=user_id))
    participant = result.scalars().first()
    if participant is None:
        if settings.require_participant_token:
            raise HTTPException(status_code=403, detail=NO_PARTICIPANT_DETAIL)
        return
    if allow_if_completed and participant.status == "completed":
        return
    if not session_id or participant.active_session_id != session_id:
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)
