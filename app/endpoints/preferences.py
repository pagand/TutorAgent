# app/endpoints/preferences.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Union
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.personalization_service import personalization_service
from app.utils.db import get_db
from app.models.enums import HintStyle, InterventionPreference

# --- Type Definitions ---
# The user can either pick a specific hint style or choose "adaptive"
HintStylePreference = Union[HintStyle, str]

# --- Router Setup ---
router = APIRouter(
    prefix="/users/{user_id}/preferences",
    tags=["User Preferences"]
)

# --- Pydantic Models ---
class Preferences(BaseModel):
    hint_style_preference: HintStylePreference = Field(
        "adaptive", 
        description="The desired hint style ('Analogy', 'Conceptual', etc.) or 'adaptive' to let the system choose."
    )
    intervention_preference: InterventionPreference = Field(
        "manual",
        description="Whether the user wants proactive hint prompts ('proactive') or not ('manual')."
    )

@router.put("/", response_model=Preferences)
async def update_preferences(user_id: str, preferences: Preferences, db: AsyncSession = Depends(get_db)):
    """Updates a user's preferences."""
    # Get the raw string value from the enum or the string itself
    hint_style_pref = preferences.hint_style_preference
    hint_style_value = hint_style_pref.value if isinstance(hint_style_pref, HintStyle) else hint_style_pref

    intervention_pref = preferences.intervention_preference
    intervention_value = intervention_pref.value if isinstance(intervention_pref, InterventionPreference) else intervention_pref

    update_data = {
        "hint_style_preference": hint_style_value,
        "intervention_preference": intervention_value
    }
    
    updated_prefs = await personalization_service.update_user_preferences(
        session=db, user_id=user_id, preferences_update=update_data
    )
    return Preferences(**updated_prefs)
