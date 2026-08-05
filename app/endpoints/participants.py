# app/endpoints/participants.py
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import ExamSession, Participant
from app.utils.db import get_db
from app.utils.logger import logger

router = APIRouter(prefix="/participants", tags=["Participants"])

STALE_SECONDS = 60  # heartbeat older than this → session considered abandoned


class TokenLoginRequest(BaseModel):
    token: str = Field(max_length=64)
    session_id: str | None = Field(None, max_length=64)  # current device's sessionId from localStorage, if any


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
        # This endpoint deliberately writes no DB rows on any path, so this
        # log line is the only trace an invalid-token probe leaves.
        logger.warning(f"participant_login: invalid token probed: '{request.token}'")
        raise HTTPException(status_code=404, detail="Invalid token")

    # Check for backend-authoritative submission first
    session_result = await db.execute(select(ExamSession).filter_by(user_id=request.token))
    exam_session = session_result.scalars().first()

    if participant.status == "completed" or (exam_session and exam_session.submitted_at):
        return TokenLoginResponse(state="completed", name=participant.name, group=participant.group)

    if exam_session is None:
        return TokenLoginResponse(state="not_started", name=participant.name, group=participant.group)

    # Session exists — check for concurrent active use on a DIFFERENT device.
    # active_session_id must be set for a lock to exist at all: POST /session/logout
    # nulls it without touching status or last_seen_at, so without this condition a
    # student who logged out is told their own token is "active on another device"
    # until last_seen_at goes stale. Mirrors the guard in session.py's start_session.
    if participant.status == "active" and participant.last_seen_at and participant.active_session_id:
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
