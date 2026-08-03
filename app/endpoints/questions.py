# Endpoints for loading questions from CSV, presenting them, and receiving answers

# app/endpoints/questions.py
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.question import PublicQuestion
from app.services.question_service import question_service # Import the service instance
from app.utils.authz import verify_session_owner
from app.utils.db import get_db
from typing import List

router = APIRouter()

def _to_public_question(question) -> PublicQuestion:
    return PublicQuestion(
        question_number=question.question_number,
        question=question.question,
        question_type=question.question_type,
        options=question.options,
        skill=question.skill,
    )

# Gated by session ownership (Stage 4.5) — without this, the full exam paper
# (all questions, options, skill labels) was downloadable by anyone before
# the exam even opened. allow_if_completed=True matches the profile/remaining
# endpoints, so /results can still fetch questions after the exam is over.
@router.get("/", response_model=List[PublicQuestion])
async def get_all_questions(user_id: str, session_id: str | None = None, db: AsyncSession = Depends(get_db)):
    await verify_session_owner(db, user_id, session_id, allow_if_completed=True)
    questions = question_service.get_all_questions()
    if not questions:
        # Service handles logging, endpoint just reports outcome
        raise HTTPException(status_code=404, detail="No questions found or loaded.")
    return [_to_public_question(q) for q in questions]

@router.get("/{question_number}", response_model=PublicQuestion)
async def get_question(question_number: int, user_id: str, session_id: str | None = None, db: AsyncSession = Depends(get_db)):
    await verify_session_owner(db, user_id, session_id, allow_if_completed=True)
    question = question_service.get_question_by_id(question_number)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return _to_public_question(question)
