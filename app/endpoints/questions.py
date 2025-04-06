# Endpoints for loading questions from CSV, presenting them, and receiving answers

# app/endpoints/questions.py
from fastapi import APIRouter, HTTPException
from app.models.question import Question
import csv
from typing import List

router = APIRouter()

# Global list to hold questions (in a real app, you might load these into a database)
QUESTIONS = []

CSV_FILE_PATH = "data/questions.csv"  # Ensure this CSV exists with the specified columns

def load_questions():
    global QUESTIONS
    try:
        with open(CSV_FILE_PATH, mode="r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            QUESTIONS = [Question(
                question_number=int(row["id"]),
                question=row["question"],
                answer1=row["answer_1"],
                answer2=row["answer_2"],
                answer3=row["answer_3"],
                answer4=row["answer_4"],
                correct_answer=row["correct_answer"],
                skill=row["skill"]
            ) for row in reader]
    except Exception as e:
        print(f"Error loading questions: {e}")

# Load questions at startup
load_questions()

@router.get("/", response_model=List[Question])
async def get_all_questions():
    if not QUESTIONS:
        raise HTTPException(status_code=404, detail="No questions found")
    return QUESTIONS

@router.get("/{question_number}", response_model=Question)
async def get_question(question_number: int):
    for q in QUESTIONS:
        if q.question_number == question_number:
            return q
    raise HTTPException(status_code=404, detail="Question not found")
