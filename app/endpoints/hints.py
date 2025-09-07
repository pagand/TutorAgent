# Endpoints to trigger hint generation (proactive/reactive) via the RAG agent
# app/endpoints/hints.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import rag_agent
from app.services.question_service import question_service
from app.state_manager import get_bkt_mastery
from app.utils.logger import logger
from app.utils.config import settings
from app.utils.db import get_db
from app.services.rag_agent import get_user_history_summary # Import the history function

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
    pre_hint_mastery: float

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f"Hint requested by user '{request.user_id}' for question {request.question_number}")

    question_obj = question_service.get_question_by_id(request.question_number)
    if not question_obj:
        raise HTTPException(status_code=404, detail="Question not found")

    skill = question_obj.skill
    pre_hint_mastery = await get_bkt_mastery(db, request.user_id, skill, settings.bkt_p_l0)
    logger.debug(f"Storing pre-hint mastery for user {request.user_id}, skill '{skill}': {pre_hint_mastery:.4f}")

    try:
        # Fetch user history using the session
        user_history = await get_user_history_summary(db, request.user_id)
        
        # Pass session and history to the RAG agent
        hint_data = await rag_agent.get_rag_hint(
            session=db,
            question_text=question_obj.question, 
            user_answer=request.user_answer, 
            user_id=request.user_id,
            user_history=user_history
        )
        generated_hint = hint_data["hint"]
        hint_style = hint_data["hint_style"]

        # The hint request itself is no longer logged separately.
        # All details will be captured in the InteractionLog when the user answers.

        if "Sorry," in generated_hint:
            logger.warning(f"RAG agent provided no specific hint for question {request.question_number}")
            generated_hint = "I couldn't generate a specific hint right now. Can you try thinking about the main concept of the question?"

        return HintResponse(
            question_number=request.question_number,
            hint=generated_hint,
            user_id=request.user_id,
            hint_style=hint_style,
            pre_hint_mastery=pre_hint_mastery
        )
    except Exception as e:
        logger.exception(f"Unhandled error in hint endpoint for question {request.question_number}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating hint")
