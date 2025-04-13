# Endpoints for loading questions from CSV, presenting them, and receiving answers

# app/endpoints/questions.py
from fastapi import APIRouter, HTTPException
from app.models.question import Question
from app.services.question_service import question_service # Import the service instance
from typing import List

router = APIRouter()

@router.get("/", response_model=List[Question])
async def get_all_questions():
    questions = question_service.get_all_questions()
    if not questions:
        # Service handles logging, endpoint just reports outcome
        raise HTTPException(status_code=404, detail="No questions found or loaded.")
    return questions

@router.get("/{question_number}", response_model=Question)
async def get_question(question_number: int):
    question = question_service.get_question_by_id(question_number)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return question