# app/endpoints/answer.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.user import InteractionLog, SkillMastery

from app.services.question_service import question_service
from app.services.bkt import bkt_service
from app.services import intervention
from app.services.personalization_service import personalization_service
from app.state_manager import get_bkt_mastery
from app.utils.authz import verify_session_owner
from app.utils.logger import logger
from app.utils.config import settings
from app.utils.db import get_db

router = APIRouter()

# Matches the InteractionLog.hint_text column width; hints are also capped at
# 200 words in the prompts (app/services/prompt_library.py), so this is the
# backstop for when the model overshoots, not the primary control.
HINT_TEXT_MAX_CHARS = 2000


class AnswerRequest(BaseModel):
    user_id: str = Field(max_length=64)
    session_id: str | None = Field(None, max_length=64)
    question_number: int = Field(ge=1)
    attempt_key: str = Field(max_length=200)
    user_answer: str | None = Field(None, max_length=500)
    skipped: bool = False
    time_taken_ms: int | None = Field(None, ge=0, le=86_400_000)

    # Hint-related fields, only present if a hint was shown
    hint_shown: bool = False
    hint_style_used: str | None = None
    hint_text: str | None = None
    pre_hint_mastery: float | None = None
    feedback_rating: int | None = Field(None, ge=1, le=5)

    @field_validator("hint_text")
    @classmethod
    def _truncate_hint_text(cls, v: str | None) -> str | None:
        """Truncates instead of rejecting an over-long hint.

        This was `Field(None, max_length=2000)`, which 422'd the entire
        submission whenever the LLM produced a hint longer than that. The
        student had taken a hint and then could neither Submit nor Skip -
        both send this field - so the question was unanswerable until they
        reloaded, which dropped the hint from the payload and let it through.
        hint_text is telemetry the client echoes back for logging, never
        exam data, so an answer must never fail because of its length.
        """
        return v if v is None or len(v) <= HINT_TEXT_MAX_CHARS else v[:HINT_TEXT_MAX_CHARS]

class AnswerResponse(BaseModel):
    correct: bool
    skill: str
    intervention_needed: bool
    intervention_reason: str | None = None
    current_mastery: float


async def _replay_response(db: AsyncSession, existing_log: InteractionLog) -> AnswerResponse:
    """Builds a response for a duplicate (already-committed) attempt_key with no mutation."""
    result = await db.execute(
        select(SkillMastery).filter_by(user_id=existing_log.user_id, skill_id=existing_log.skill)
    )
    skill_mastery = result.scalars().first()
    current_mastery = skill_mastery.mastery_level if skill_mastery else settings.bkt_p_l0
    consecutive_errors = skill_mastery.consecutive_errors if skill_mastery else 0
    consecutive_skips = skill_mastery.consecutive_skips if skill_mastery else 0

    intervention_reason = intervention.check_intervention(
        existing_log.user_id,
        existing_log.skill,
        existing_log.time_taken_ms,
        current_mastery=current_mastery,
        consecutive_errors=consecutive_errors,
        consecutive_skips=consecutive_skips
    )

    return AnswerResponse(
        correct=bool(existing_log.is_correct),
        skill=existing_log.skill,
        intervention_needed=intervention_reason is not None,
        intervention_reason=intervention_reason,
        current_mastery=current_mastery
    )


@router.post("/", response_model=AnswerResponse)
async def submit_answer(request: AnswerRequest, db: AsyncSession = Depends(get_db)):
    await verify_session_owner(db, request.user_id, request.session_id)
    user_id = request.user_id
    q_id = request.question_number
    user_ans = request.user_answer
    time_taken = request.time_taken_ms

    # Idempotency: a retried submission carrying the same attempt_key (e.g. after
    # a lost response) returns the already-committed outcome instead of being
    # processed a second time, so it can never be miscounted as a second real attempt.
    replay_result = await db.execute(
        select(InteractionLog).filter_by(user_id=user_id, question_id=q_id, attempt_key=request.attempt_key)
    )
    existing_log = replay_result.scalars().first()
    if existing_log is not None:
        return await _replay_response(db, existing_log)

    question = question_service.get_question_by_id(q_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    skill = question.skill

    # Server-side attempt cap, scoped per-question (not per-skill — SkillMastery's
    # consecutive_errors spans every question sharing a skill, so it cannot be used
    # here without incorrectly locking unrelated questions). Once answered
    # correctly, or once 2 real (non-skip) attempts exist with none correct,
    # the question is locked read-only and no further submission is accepted.
    prior_attempts_result = await db.execute(
        select(InteractionLog)
        .filter_by(user_id=user_id, question_id=q_id)
        .where(InteractionLog.user_answer.isnot(None))
    )
    prior_attempts = prior_attempts_result.scalars().all()
    already_correct = any(log.is_correct for log in prior_attempts)
    if already_correct:
        raise HTTPException(status_code=409, detail="This question is already answered correctly and is locked.")
    if len(prior_attempts) >= 2:
        raise HTTPException(status_code=409, detail="This question is locked after 2 incorrect attempts.")

    if request.skipped:
        is_correct = False
    else:
        if user_ans is None:
            raise HTTPException(status_code=422, detail="user_answer cannot be null if skipped is false")
        is_correct = question_service.check_answer(question, user_ans)

    result = await db.execute(select(SkillMastery).filter_by(user_id=user_id, skill_id=skill))
    skill_mastery = result.scalars().first()

    if not skill_mastery:
        skill_mastery = SkillMastery(
            user_id=user_id,
            skill_id=skill,
            mastery_level=settings.bkt_p_l0,
            consecutive_errors=0,
            consecutive_skips=0
        )
        db.add(skill_mastery)
        await db.flush()

    if not request.skipped:
        updated_mastery_level = await bkt_service.update_mastery(user_id, skill, is_correct, existing_skill_mastery=skill_mastery)
    else:
        updated_mastery_level = skill_mastery.mastery_level

    bkt_change_value = None
    if request.hint_shown:
        if request.pre_hint_mastery is None or request.hint_style_used is None:
            raise HTTPException(
                status_code=422,
                detail="If hint_shown is true, pre_hint_mastery and hint_style_used must be provided."
            )

        if not request.skipped:
            bkt_change_value = updated_mastery_level - request.pre_hint_mastery

        await personalization_service.record_feedback(
            session=db,
            user_id=user_id,
            hint_style=request.hint_style_used,
            bkt_change=bkt_change_value or 0,
            rating=request.feedback_rating
        )
        logger.debug(f"Recorded hybrid feedback for user {user_id} on skill {skill}. BKT change: {bkt_change_value}, Rating: {request.feedback_rating}")

    log_entry = InteractionLog(
        user_id=user_id,
        question_id=q_id,
        skill=skill,
        attempt_key=request.attempt_key,
        user_answer=user_ans,
        is_correct=is_correct,
        time_taken_ms=time_taken,
        hint_shown=request.hint_shown,
        hint_style_used=request.hint_style_used,
        hint_text=request.hint_text,
        user_feedback_rating=request.feedback_rating,
        bkt_change=bkt_change_value
    )
    db.add(log_entry)

    if request.skipped:
        skill_mastery.consecutive_skips += 1
        skill_mastery.consecutive_errors = 0
    elif is_correct:
        skill_mastery.consecutive_skips = 0
        skill_mastery.consecutive_errors = 0
    else:
        skill_mastery.consecutive_skips = 0
        skill_mastery.consecutive_errors += 1
    db.add(skill_mastery)

    intervention_reason = intervention.check_intervention(
        user_id,
        skill,
        time_taken,
        current_mastery=updated_mastery_level,
        consecutive_errors=skill_mastery.consecutive_errors,
        consecutive_skips=skill_mastery.consecutive_skips
    )

    try:
        await db.commit()
    except IntegrityError:
        # Two requests with the same attempt_key raced each other; the loser
        # rolls back and returns the winner's already-committed outcome.
        await db.rollback()
        replay_result = await db.execute(
            select(InteractionLog).filter_by(user_id=user_id, question_id=q_id, attempt_key=request.attempt_key)
        )
        existing_log = replay_result.scalars().first()
        if existing_log is not None:
            return await _replay_response(db, existing_log)
        raise HTTPException(status_code=503, detail="Answer could not be recorded. Please retry.")

    return AnswerResponse(
        correct=is_correct,
        skill=skill,
        intervention_needed=intervention_reason is not None,
        intervention_reason=intervention_reason,
        current_mastery=updated_mastery_level
    )
