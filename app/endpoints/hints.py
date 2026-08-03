# app/endpoints/hints.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from sqlalchemy import select

from app.services import rag_agent
from app.services.question_service import question_service
from app.services.personalization_service import personalization_service
from app.services.llm_quota import reserve_llm_call
from app.state_manager import get_bkt_mastery
from app.utils.authz import verify_session_owner
from app.utils.logger import logger
from app.utils.config import settings
from app.utils.db import get_db
from app.services.rag_agent import get_user_history_summary

router = APIRouter()

class HintRequest(BaseModel):
    user_id: str = Field(max_length=64)
    session_id: str | None = Field(None, max_length=64)
    question_number: int = Field(ge=1)
    user_answer: str | None = Field(None, max_length=500)

class HintResponse(BaseModel):
    question_number: int
    hint: str
    user_id: str
    hint_style: str
    pre_hint_mastery: float

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest, db: AsyncSession = Depends(get_db)):
    await verify_session_owner(db, request.user_id, request.session_id)
    logger.debug(f"Hint requested by user '{request.user_id}' for question {request.question_number}")

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
    user_history = await get_user_history_summary(db, request.user_id)
    hint_style = await personalization_service.get_adaptive_hint_style(db, request.user_id)

    # Reserve the call against the per-user/global daily LLM cap before it
    # runs - a call that then errors out on the Gemini side still counts.
    await reserve_llm_call(db, request.user_id, "hint")

    # Release the DB connection before the slow LLM call so the pool isn't exhausted
    await db.commit()

    try:
        hint_data = await rag_agent.get_rag_hint(
            question_id=question_obj.question_number,
            user_answer=request.user_answer,
            user_id=request.user_id,
            user_history=user_history,
            hint_style=hint_style,
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
        )
    except Exception as e:
        logger.exception(f"Unhandled error in hint endpoint for question {request.question_number}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating hint")
