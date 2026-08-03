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
# entry) are exempt - there is no lock to enforce for identities the exam
# manifest never issued a token for.
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Participant

FORBIDDEN_DETAIL = "This exam token is not active on this device."


async def verify_session_owner(
    db: AsyncSession,
    user_id: str,
    session_id: str | None,
    *,
    allow_if_completed: bool = False,
) -> None:
    """Raises 403 unless session_id matches the participant's active device lock.

    No-op when user_id has no Participant row (ad-hoc/dev/test identity).
    When allow_if_completed is True, a participant whose exam is already
    completed is exempt too - used for read endpoints (profile, results)
    that legitimately need to work from a different device after the exam
    is over, e.g. a student checking their results on their phone.
    """
    result = await db.execute(select(Participant).filter_by(token=user_id))
    participant = result.scalars().first()
    if participant is None:
        return
    if allow_if_completed and participant.status == "completed":
        return
    if not session_id or participant.active_session_id != session_id:
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)
