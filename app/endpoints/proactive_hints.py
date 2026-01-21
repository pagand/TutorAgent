# app/endpoints/proactive_hints.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import SkillMastery, User
from app.services.question_service import question_service
from app.services import intervention
from app.utils.logger import logger
from app.utils.config import settings
from app.utils.db import get_db

router = APIRouter(
    tags=["Intervention"]
)

class InterventionCheckRequest(BaseModel):
    user_id: str
    question_number: int
    time_spent_ms: int

class InterventionCheckResponse(BaseModel):
    intervention_needed: bool

@router.post("/intervention-check", response_model=InterventionCheckResponse)
async def check_for_intervention(request: InterventionCheckRequest, db: AsyncSession = Depends(get_db)):
    """
    Checks if a proactive intervention is needed for a user based on their
    current state and time spent on a question.
    """
    user_id = request.user_id
    q_id = request.question_number
    time_spent = request.time_spent_ms

    # 1. Fetch the user to check their preferences
    user_result = await db.execute(select(User).filter_by(id=user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2. Only proceed if the user's preference is "proactive" and hints are not disabled
    user_prefs = user.preferences
    if user_prefs.get("intervention_preference") != "proactive" or user_prefs.get("hint_style_preference") == "none":
        return InterventionCheckResponse(intervention_needed=False)

    # 3. Get the question to find the relevant skill
    question = question_service.get_question_by_id(q_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    skill = question.skill

    # 4. Fetch the user's current mastery and error count for that skill
    mastery_result = await db.execute(select(SkillMastery).filter_by(user_id=user_id, skill_id=skill))
    skill_mastery = mastery_result.scalars().first()

    # If there's no record, use default values
    if not skill_mastery:
        current_mastery = settings.bkt_p_l0
        consecutive_errors = 0
        consecutive_skips = 0
    else:
        current_mastery = skill_mastery.mastery_level
        consecutive_errors = skill_mastery.consecutive_errors
        consecutive_skips = skill_mastery.consecutive_skips

    # 5. Call the enhanced intervention logic
    is_needed = intervention.check_intervention(
        user_id=user_id,
        skill=skill,
        time_taken_ms=time_spent,
        current_mastery=current_mastery,
        consecutive_errors=consecutive_errors,
        consecutive_skips=consecutive_skips
    )

    return InterventionCheckResponse(intervention_needed=is_needed)
