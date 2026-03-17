# app/endpoints/action_log.py
# Receives fine-grained user interaction events from the frontend.
# Every click, navigation, selection, and system event is logged here for analysis.
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserActionLog, InterventionLog
from app.utils.db import get_db
from app.utils.logger import logger

router = APIRouter(prefix="/log", tags=["Logging"])

# Valid action types — documented for frontend reference
ACTION_TYPES = {
    "session_start",
    "session_complete",
    "timer_expired",
    "question_view",
    "question_navigate",
    "choice_select",
    "answer_submit",
    "answer_skip",
    "hint_request",
    "hint_display",
    "hint_feedback",
    "intervention_offered",
    "intervention_accepted",
    "intervention_rejected",
    "chat_message_sent",
    "chat_response_received",
    "profile_view",
    "preference_update",
}


class ActionLogRequest(BaseModel):
    user_id: str
    session_id: str
    action_type: str
    question_number: int | None = None
    action_data: dict[str, Any] = {}


class ActionLogResponse(BaseModel):
    logged: bool


class InterventionLogRequest(BaseModel):
    user_id: str
    session_id: str
    question_number: int
    time_on_question_ms: int
    mastery_at_trigger: float | None = None
    accepted: bool | None = None  # None = just offered, True/False = response


@router.post("/action", response_model=ActionLogResponse)
async def log_action(request: ActionLogRequest, db: AsyncSession = Depends(get_db)):
    """
    Logs any user action. Called by the frontend for every meaningful interaction.
    Unknown action_types are still logged (with a warning) to avoid data loss.
    """
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
            accepted=request.accepted,
        )
        db.add(entry)

    await db.commit()
    logger.debug(
        f"Logged intervention for user {request.user_id} q={request.question_number} "
        f"accepted={request.accepted}"
    )
    return ActionLogResponse(logged=True)
