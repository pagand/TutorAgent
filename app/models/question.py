# Data model for questions
from pydantic import BaseModel
from typing import List, Optional

class Question(BaseModel):
    question_number: int
    question: str
    question_type: str  # 'multiple_choice' or 'fill_in_the_blank'
    options: Optional[List[str]] = None  # For multiple_choice
    correct_answer: str
    skill: str
