# app/endpoints/answer.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict

from app.services.question_service import question_service
from app.services.bkt import bkt_service
from app.services import intervention
from app.state_manager import add_log_entry
from app.utils.logger import logger
from app.utils.config import settings

router = APIRouter()

class AnswerRequest(BaseModel):
    user_id: str
    question_number: int
    user_answer: str # Assuming answer is the choice index, e.g., "1", "2", "3", "4"
    time_taken_ms: int | None = None

class AnswerResponse(BaseModel):
    correct: bool
    correct_answer: str # Send back the correct answer index
    skill: str
    intervention_needed: bool
    current_mastery: float # Send back updated mastery

@router.post("/", response_model=AnswerResponse)
async def submit_answer(request: AnswerRequest):
    user_id = request.user_id
    q_id = request.question_number
    user_ans = request.user_answer
    time_taken = request.time_taken_ms

    # 1. Get Question Details
    question = question_service.get_question_by_id(q_id)
    if not question:
        logger.warning(f"Answer submitted for non-existent question ID: {q_id}")
        raise HTTPException(status_code=404, detail="Question not found")

    skill = question.skill

    # 2. Check Correctness
    is_correct = question_service.check_answer(q_id, user_ans)
    if is_correct is None: # Should not happen if question exists, but safeguard
         logger.error(f"Failed to check answer validity for question ID: {q_id}")
         raise HTTPException(status_code=500, detail="Error checking answer")

    # 3. Log the Interaction (including correctness and time)
    log_data = {
        "action": "answered",
        "question_id": q_id,
        "skill": skill,
        "user_answer": user_ans,
        "is_correct": is_correct,
        "time_taken_ms": time_taken,
    }
    add_log_entry(user_id, log_data) # This also updates consecutive errors

    # 4. Update BKT Mastery
    try:
        bkt_service.update_mastery(user_id, skill, is_correct)
    except Exception as e:
        logger.exception(f"Error updating BKT for user {user_id}, skill {skill}: {e}")
        # Decide how to handle - proceed without update or raise error?
        # For POC, log error and proceed

    # 5. Check for Intervention Need
    intervention_needed = False
    try:
         intervention_needed = intervention.check_intervention(user_id, skill, time_taken)
    except Exception as e:
        logger.exception(f"Error checking intervention for user {user_id}, skill {skill}: {e}")
        # Decide default behavior on error - safer to assume no intervention needed
        intervention_needed = False


    # 6. Prepare and Return Response
    # Get the latest mastery AFTER the update
    from app.state_manager import get_bkt_mastery # Import locally to avoid circular dependency potential
    current_mastery = get_bkt_mastery(user_id, skill, settings.bkt_p_l0)

    return AnswerResponse(
        correct=is_correct,
        correct_answer=str(question.correct_answer),
        skill=skill,
        intervention_needed=intervention_needed,
        current_mastery=current_mastery
    )