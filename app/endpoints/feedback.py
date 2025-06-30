# app/endpoints/feedback.py
from fastapi import APIRouter
from pydantic import BaseModel
from app.services.personalization_service import personalization_service
from app.utils.logger import logger

router = APIRouter()

class Feedback(BaseModel):
    user_id: str
    question_id: int
    hint_style: str # The style of hint that was shown
    rating: int # e.g., 1-5 rating
    comment: str | None = None

@router.post("/")
async def submit_feedback(feedback: Feedback):
    """Receives feedback from the user and records it."""
    logger.info(f"Received feedback from user {feedback.user_id} for question {feedback.question_id}: {feedback.dict()}")
    
    # Record the feedback using the personalization service
    personalization_service.record_feedback(
        user_id=feedback.user_id,
        hint_style=feedback.hint_style,
        rating=feedback.rating
    )
    
    return {"message": "Feedback received and recorded"}