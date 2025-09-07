# app/endpoints/users.py
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.question_service import question_service
from app.state_manager import get_bkt_mastery, get_user_or_create, get_user_profile_with_session
from app.utils.config import settings
from app.utils.logger import logger
from app.utils.db import get_db
from app.models.user import User

router = APIRouter(
    tags=["Users"]
)

class UserCreate(BaseModel):
    user_id: str

@router.post("/", response_model=dict)
async def create_user(user_create: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new user with default profile settings. If user already exists,
    it returns the existing user's profile.
    """
    logger.debug(f"Attempting to create or fetch user: {user_create.user_id}")
    user = await get_user_or_create(db, user_create.user_id)
    
    # We need to flush to get the user's ID and default values before reading the profile
    await db.flush()
    await db.refresh(user)
    
    # Now, commit the transaction to permanently save the new user
    await db.commit()
    
    # Use the same session to get the full profile
    return await get_user_profile_with_session(db, user_create.user_id)

@router.get("/{user_id}/bkt", response_model=Dict[str, float])
async def get_user_bkt_state(user_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves the current Bayesian Knowledge Tracing (BKT) mastery state
    for a given user across all known skills.
    """
    logger.debug(f"Fetching BKT state for user_id: {user_id}")
    all_skills = question_service.get_all_skills()
    if not all_skills:
        logger.warning("No skills loaded from question service. Cannot determine BKT state.")
        return {}

    bkt_state: Dict[str, float] = {}
    for skill in all_skills:
        mastery = await get_bkt_mastery(user_id, skill, settings.bkt_p_l0)
        bkt_state[skill] = mastery

    logger.debug(f"Returning BKT state for user {user_id}: {bkt_state}")
    return bkt_state

@router.get("/{user_id}/profile", response_model=dict)
async def get_user_profile_endpoint(user_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves a consolidated user profile from the database.
    """
    logger.debug(f"Fetching profile for user_id: {user_id}")
    profile = await get_user_profile_with_session(db, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile
