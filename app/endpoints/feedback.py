#  Endpoints for receiving user feedback on hints and answers
# app/endpoints/feedback.py
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class FeedbackRequest(BaseModel):
    question_number: int
    hint: str
    rating: int  # e.g., rating from 1 to 5
    comment: str = None

@router.post("/")
async def submit_feedback(feedback: FeedbackRequest):
    # For now, simply print the feedback.
    # Later, this feedback can be stored in the DB and used to update personalization.
    print(f"Received feedback: {feedback}")
    return {"status": "Feedback received"}
