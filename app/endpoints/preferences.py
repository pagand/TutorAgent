# app/endpoints/preferences.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.personalization_service import personalization_service
from app.utils.db import get_db
from app.models.enums import HintStyle

router = APIRouter(
    prefix="/users/{user_id}/preferences",
    tags=["User Preferences"]
)

class Preferences(BaseModel):
    preferred_hint_style: HintStyle
    feedback_preference: str = "immediate" # Keep for compatibility, though not used in DB model yet

@router.put("/", response_model=Preferences)
async def update_preferences(user_id: str, preferences: Preferences, db: AsyncSession = Depends(get_db)):
    """Updates a user's preferences."""
    updated_prefs = await personalization_service.update_user_preferences(
        session=db, user_id=user_id, preferences_update=preferences.dict()
    )
    # Commit the transaction to save the changes
    await db.commit()
    return Preferences(**updated_prefs)