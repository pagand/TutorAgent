# app/endpoints/preferences.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.services.personalization_service import personalization_service

router = APIRouter()

class Preferences(BaseModel):
    preferred_hint_style: str
    feedback_preference: str

@router.get("/{user_id}/preferences", response_model=Preferences)
async def get_preferences(user_id: str):
    """Gets user preferences."""
    return personalization_service.get_user_preferences(user_id)

@router.put("/{user_id}/preferences", response_model=Preferences)
async def update_preferences(user_id: str, preferences: Preferences):
    """Updates user preferences."""
    return personalization_service.update_user_preferences(user_id, preferences.dict())
