# app/endpoints/participants.py
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import ExamSession, Participant
from app.utils.db import get_db

router = APIRouter(prefix="/participants", tags=["Participants"])

STALE_SECONDS = 60  # heartbeat older than this → session considered abandoned


class TokenLoginRequest(BaseModel):
    token: str
    session_id: str | None = None  # current device's sessionId from localStorage, if any


class TokenLoginResponse(BaseModel):
    state: str  # not_started | resumable | active_elsewhere | completed
    name: str | None = None
    group: str | None = None


@router.post("/login", response_model=TokenLoginResponse)
async def participant_login(request: TokenLoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Read-only probe — returns the state for a token without creating any DB rows.
    Accepts an optional session_id so the same device after a tab-close is treated
    as 'resumable' rather than 'active_elsewhere'.
    """
    result = await db.execute(select(Participant).filter_by(token=request.token))
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Invalid token")

    # Check for backend-authoritative submission first
    session_result = await db.execute(select(ExamSession).filter_by(user_id=request.token))
    exam_session = session_result.scalars().first()

    if participant.status == "completed" or (exam_session and exam_session.submitted_at):
        return TokenLoginResponse(state="completed", name=participant.name, group=participant.group)

    if exam_session is None:
        return TokenLoginResponse(state="not_started", name=participant.name, group=participant.group)

    # Session exists — check for concurrent active use on a DIFFERENT device
    if participant.status == "active" and participant.last_seen_at:
        age_seconds = (datetime.now(timezone.utc).replace(tzinfo=None) - participant.last_seen_at).total_seconds()
        if age_seconds < STALE_SECONDS:
            # If the caller's sessionId matches the active lock → same device, resumable
            same_device = (
                request.session_id is not None
                and request.session_id != ""
                and request.session_id == participant.active_session_id
            )
            if not same_device:
                return TokenLoginResponse(state="active_elsewhere", name=participant.name, group=participant.group)

    return TokenLoginResponse(state="resumable", name=participant.name, group=participant.group)
