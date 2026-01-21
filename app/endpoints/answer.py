# app/endpoints/answer.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import InteractionLog, SkillMastery

from app.services.question_service import question_service
from app.services.bkt import bkt_service
from app.services import intervention
from app.services.personalization_service import personalization_service
from app.state_manager import get_bkt_mastery
from app.utils.logger import logger
from app.utils.config import settings
from app.utils.db import get_db

router = APIRouter()

class AnswerRequest(BaseModel):
    user_id: str
    question_number: int
    user_answer: str | None = None
    skipped: bool = False
    time_taken_ms: int | None = None
    
    # Hint-related fields, only present if a hint was shown
    hint_shown: bool = False
    hint_style_used: str | None = None
    hint_text: str | None = None
    pre_hint_mastery: float | None = None
    feedback_rating: int | None = Field(None, ge=1, le=5)

class AnswerResponse(BaseModel):
    correct: bool
    correct_answer: str
    skill: str
    intervention_needed: bool
    current_mastery: float

@router.post("/", response_model=AnswerResponse)
async def submit_answer(request: AnswerRequest, db: AsyncSession = Depends(get_db)):
    user_id = request.user_id
    q_id = request.question_number
    user_ans = request.user_answer
    time_taken = request.time_taken_ms

    question = question_service.get_question_by_id(q_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    skill = question.skill
    
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
        logger.info(f"Recorded hybrid feedback for user {user_id} on skill {skill}. BKT change: {bkt_change_value}, Rating: {request.feedback_rating}")

    log_entry = InteractionLog(
        user_id=user_id,
        question_id=q_id,
        skill=skill,
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

    intervention_needed = intervention.check_intervention(
        user_id, 
        skill, 
        time_taken,
        current_mastery=updated_mastery_level,
        consecutive_errors=skill_mastery.consecutive_errors,
        consecutive_skips=skill_mastery.consecutive_skips
    )

    await db.commit()

    return AnswerResponse(
        correct=is_correct,
        correct_answer=str(question.correct_answer),
        skill=skill,
        intervention_needed=intervention_needed,
        current_mastery=updated_mastery_level
    )

