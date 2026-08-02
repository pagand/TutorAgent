# Endpoints for loading questions from CSV, presenting them, and receiving answers

# app/endpoints/questions.py
from fastapi import APIRouter, HTTPException
from app.models.question import PublicQuestion
from app.services.question_service import question_service # Import the service instance
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

@router.get("/", response_model=List[PublicQuestion])
async def get_all_questions():
    questions = question_service.get_all_questions()
    if not questions:
        # Service handles logging, endpoint just reports outcome
        raise HTTPException(status_code=404, detail="No questions found or loaded.")
    return [_to_public_question(q) for q in questions]

@router.get("/{question_number}", response_model=PublicQuestion)
async def get_question(question_number: int):
    question = question_service.get_question_by_id(question_number)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return _to_public_question(question)
