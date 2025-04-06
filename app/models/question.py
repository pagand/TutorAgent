# Data model for questions (CSV structure: question number, question text, answer 1-4, correct answer, skill)
from pydantic import BaseModel

class Question(BaseModel):
    question_number: int
    question: str
    answer1: str
    answer2: str
    answer3: str
    answer4: str
    correct_answer: str
    skill: str