# app/endpoints/answer.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.question_service import question_service
from app.services.bkt import bkt_service
from app.services import intervention
from app.services.personalization_service import personalization_service
from app.state_manager import add_log_entry, get_user_state, get_bkt_mastery
from app.utils.logger import logger
from app.utils.config import settings

router = APIRouter()

class AnswerRequest(BaseModel):
    user_id: str
    question_number: int
    user_answer: str
    time_taken_ms: int | None = None
    hint_shown: bool = False # New field to track if a hint was used

class AnswerResponse(BaseModel):
    correct: bool
    correct_answer: str
    skill: str
    intervention_needed: bool
    current_mastery: float

@router.post("/", response_model=AnswerResponse)
async def submit_answer(request: AnswerRequest):
    user_id = request.user_id
    q_id = request.question_number
    user_ans = request.user_answer
    time_taken = request.time_taken_ms

    question = question_service.get_question_by_id(q_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    skill = question.skill
    is_correct = question_service.check_answer(q_id, user_ans)

    # --- Post-Hint Performance Tracking ---
    user_state = get_user_state(user_id)
    pre_hint_mastery = user_state.get("pre_hint_mastery", {}).pop(skill, None)

    if request.hint_shown and pre_hint_mastery is not None:
        # Get mastery *before* the update for the current answer
        current_mastery_before_update = get_bkt_mastery(user_id, skill, settings.bkt_p_l0)
        bkt_change = current_mastery_before_update - pre_hint_mastery
        
        # Record feedback with BKT change (rating is 0 as it's implicit)
        personalization_service.record_feedback(
            user_id=user_id,
            hint_style=user_state.get("last_hint_style", "Unknown"), # Get the style that was shown
            rating=3, # Use a neutral rating for implicit feedback
            bkt_change=bkt_change
        )
        logger.info(f"Recorded implicit feedback for user {user_id} on skill {skill}. BKT change: {bkt_change:.4f}")

    # Log interaction *before* BKT update to get mastery state prior to this answer
    log_data = {
        "action": "answered",
        "question_id": q_id,
        "skill": skill,
        "user_answer": user_ans,
        "is_correct": is_correct,
        "time_taken_ms": time_taken,
    }
    add_log_entry(user_id, log_data)

    # Update BKT Mastery
    bkt_service.update_mastery(user_id, skill, is_correct)

    # Check for Intervention Need
    intervention_needed = intervention.check_intervention(user_id, skill, time_taken)

    current_mastery = get_bkt_mastery(user_id, skill, settings.bkt_p_l0)

    return AnswerResponse(
        correct=is_correct,
        correct_answer=str(question.correct_answer),
        skill=skill,
        intervention_needed=intervention_needed,
        current_mastery=current_mastery
    )
