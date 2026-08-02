# app/endpoints/action_log.py
# Receives fine-grained user interaction events from the frontend.
# Every click, navigation, selection, and system event is logged here for analysis.
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserActionLog, InterventionLog
from app.utils.authz import verify_session_owner
from app.utils.db import get_db
from app.utils.logger import logger

router = APIRouter(prefix="/log", tags=["Logging"])

# Valid action types — canonical {entity}_{verb} naming
ACTION_TYPES = {
    # Session lifecycle
    "session_start",
    "session_complete",   # auto-complete (all done)
    "session_submit",     # student submits early
    "session_expire",     # timer hits zero
    "timer_warning",      # 3-minute warning fired
    # Question navigation
    "question_view",
    "question_navigate",
    # Answer interactions
    "choice_select",      # MC option clicked (before submit)
    "answer_focus",       # fill-in-blank input focused
    "answer_submit",
    "answer_skip",
    # Hint interactions
    "hint_request",
    "hint_display",
    "hint_feedback",      # star rating clicked
    # Intervention interactions
    "intervention_offer",
    "intervention_accept",
    "intervention_reject",
    # Chat interactions
    "chat_send",
    # Profile interactions
    "profile_view",
    "preference_update",
    # Legacy names kept for backward compatibility
    "timer_expired",
    "intervention_offered",
    "intervention_accepted",
    "intervention_rejected",
    "chat_message_sent",
    "chat_response_received",
}


class ActionLogRequest(BaseModel):
    user_id: str
    session_id: str
    action_type: str = Field(max_length=100)
    question_number: int | None = None
    action_data: dict[str, Any] = {}

    @field_validator("action_data")
    @classmethod
    def bound_action_data_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > 5000:
            raise ValueError("action_data is too large")
        return v


class ActionLogResponse(BaseModel):
    logged: bool


class InterventionLogRequest(BaseModel):
    user_id: str
    session_id: str
    question_number: int
    time_on_question_ms: int
    mastery_at_trigger: float | None = None
    reason: str | None = None  # time_spent | low_mastery | consecutive_errors | consecutive_skips
    accepted: bool | None = None  # None = just offered, True/False = response


@router.post("/action", response_model=ActionLogResponse)
async def log_action(request: ActionLogRequest, db: AsyncSession = Depends(get_db)):
    """
    Logs any user action. Called by the frontend for every meaningful interaction.
    Unknown action_types are still logged (with a warning) to avoid data loss.
    """
    await verify_session_owner(db, request.user_id, request.session_id)
    if request.action_type not in ACTION_TYPES:
        logger.warning(f"Unknown action_type '{request.action_type}' from user {request.user_id}")

    entry = UserActionLog(
        user_id=request.user_id,
        session_id=request.session_id,
        action_type=request.action_type,
        question_number=request.question_number,
        action_data=request.action_data,
    )
    db.add(entry)
    await db.commit()

    logger.debug(
        f"Logged action '{request.action_type}' for user {request.user_id} "
        f"q={request.question_number} data={request.action_data}"
    )
    return ActionLogResponse(logged=True)


@router.post("/intervention", response_model=ActionLogResponse)
async def log_intervention(request: InterventionLogRequest, db: AsyncSession = Depends(get_db)):
    """
    Logs a proactive intervention event. Call once when offered (accepted=None),
    then again when the user responds (accepted=True/False).
    Uses upsert-like logic: if a record exists for (user_id, question_number) with
    accepted=None, update it; otherwise insert a new row.
    """
    await verify_session_owner(db, request.user_id, request.session_id)
    from sqlalchemy.future import select

    result = await db.execute(
        select(InterventionLog).filter_by(
            user_id=request.user_id,
            question_number=request.question_number,
            accepted=None,
        ).order_by(InterventionLog.timestamp.desc()).limit(1)
    )
    existing = result.scalars().first()

    if existing and request.accepted is not None:
        existing.accepted = request.accepted
        db.add(existing)
    else:
        entry = InterventionLog(
            user_id=request.user_id,
            session_id=request.session_id,
            question_number=request.question_number,
            time_on_question_ms=request.time_on_question_ms,
            mastery_at_trigger=request.mastery_at_trigger,
            reason=request.reason,
            accepted=request.accepted,
        )
        db.add(entry)

    await db.commit()
    logger.debug(
        f"Logged intervention for user {request.user_id} q={request.question_number} "
        f"reason={request.reason} accepted={request.accepted}"
    )
    return ActionLogResponse(logged=True)
