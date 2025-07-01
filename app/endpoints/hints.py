# Endpoints to trigger hint generation (proactive/reactive) via the RAG agent
# app/endpoints/hints.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services import rag_agent
from app.services.question_service import question_service
from app.state_manager import get_user_state, get_bkt_mastery
from app.utils.logger import logger
from app.utils.config import settings

router = APIRouter()

class HintRequest(BaseModel):
    user_id: str
    question_number: int
    user_answer: str | None = None

class HintResponse(BaseModel):
    question_number: int
    hint: str
    user_id: str
    hint_style: str

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest):
    logger.info(f"Hint requested by user '{request.user_id}' for question {request.question_number}")

    question_obj = question_service.get_question_by_id(request.question_number)
    if not question_obj:
        raise HTTPException(status_code=404, detail="Question not found")

    # --- Pre-Hint Performance Tracking ---
    # Store the user's BKT mastery *before* they receive the hint
    skill = question_obj.skill
    user_state = get_user_state(request.user_id)
    pre_hint_mastery = get_bkt_mastery(request.user_id, skill, settings.bkt_p_l0)
    
    if "pre_hint_mastery" not in user_state:
        user_state["pre_hint_mastery"] = {}
    user_state["pre_hint_mastery"][skill] = pre_hint_mastery
    logger.debug(f"Stored pre-hint mastery for user {request.user_id}, skill '{skill}': {pre_hint_mastery:.4f}")

    try:
        hint_data = await rag_agent.get_rag_hint(question_obj.question, request.user_answer, request.user_id)
        generated_hint = hint_data["hint"]
        hint_style = hint_data["hint_style"]

        # Store the style of the hint that was given, to be used for feedback
        user_state["last_hint_style"] = hint_style

        if "Sorry," in generated_hint:
            logger.warning(f"RAG agent provided no specific hint for question {request.question_number}")
            generated_hint = "I couldn't generate a specific hint right now. Can you try thinking about the main concept of the question?"

        return HintResponse(
            question_number=request.question_number,
            hint=generated_hint,
            user_id=request.user_id,
            hint_style=hint_style
        )
    except Exception as e:
        logger.exception(f"Unhandled error in hint endpoint for question {request.question_number}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating hint")