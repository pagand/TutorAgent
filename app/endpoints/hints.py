# Endpoints to trigger hint generation (proactive/reactive) via the RAG agent
# app/endpoints/hints.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from sqlalchemy import select

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
    context: str | None = None
    final_prompt: str | None = None

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f"Hint requested by user '{request.user_id}' for question {request.question_number}")

    user_result = await db.execute(select(User).filter_by(id=request.user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.preferences.get("hint_style_preference") == "none":
        raise HTTPException(status_code=403, detail="Hints are disabled for this user.")

    question_obj = question_service.get_question_by_id(request.question_number)
    if not question_obj:
        raise HTTPException(status_code=404, detail="Question not found")

    skill = question_obj.skill
    pre_hint_mastery = await get_bkt_mastery(db, request.user_id, skill, settings.bkt_p_l0)
    logger.debug(f"Storing pre-hint mastery for user {request.user_id}, skill '{skill}': {pre_hint_mastery:.4f}")

    try:
        user_history = await get_user_history_summary(db, request.user_id)
        
        hint_data = await rag_agent.get_rag_hint(
            session=db,
            question_id=question_obj.question_number,
            user_answer=request.user_answer, 
            user_id=request.user_id,
            user_history=user_history
        )

        if "Sorry," in hint_data["hint"]:
            logger.warning(f"RAG agent provided no specific hint for question {request.question_number}")
            hint_data["hint"] = "I couldn't generate a specific hint right now. Can you try thinking about the main concept of the question?"

        return HintResponse(
            question_number=request.question_number,
            hint=hint_data.get("hint"),
            user_id=request.user_id,
            hint_style=hint_data.get("hint_style"),
            pre_hint_mastery=pre_hint_mastery,
            context=hint_data.get("context"),
            final_prompt=hint_data.get("final_prompt")
        )
    except Exception as e:
        logger.exception(f"Unhandled error in hint endpoint for question {request.question_number}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating hint")
