# app/state_manager.py
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.user import User, SkillMastery, InteractionLog
from app.utils.db import AsyncSessionLocal
from app.utils.logger import logger
from datetime import datetime
from app.utils.config import settings
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession



async def get_user_or_create(session: AsyncSession, user_id: str) -> User:
    """
    Fetches a user from the DB or creates a new one and adds it to the session.
    The calling function is responsible for committing the transaction.
    """
    result = await session.execute(select(User).filter_by(id=user_id))
    user = result.scalars().first()
    if not user:
        logger.info(f"Adding new user '{user_id}' to session.")
        user = User(id=user_id)
        session.add(user)
    return user

async def get_bkt_mastery(session: AsyncSession, user_id: str, skill: str, default_mastery: float) -> float:
    """Gets BKT mastery for a skill from the database using the provided session."""
    result = await session.execute(
        select(SkillMastery.mastery_level)
        .filter_by(user_id=user_id, skill_id=skill)
    )
    mastery = result.scalars().first()
    return mastery if mastery is not None else default_mastery

async def update_bkt_mastery(user_id: str, skill: str, new_mastery: float):
    """Updates the stored BKT mastery for a skill in the database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SkillMastery).filter_by(user_id=user_id, skill_id=skill)
        )
        skill_mastery = result.scalars().first()
        if skill_mastery:
            skill_mastery.mastery_level = new_mastery
        else:
            skill_mastery = SkillMastery(user_id=user_id, skill_id=skill, mastery_level=new_mastery)
            session.add(skill_mastery)
        await session.commit()

async def get_user_profile_with_session(session: AsyncSession, user_id: str) -> dict:
    """Retrieves a consolidated user profile using provided session."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.skill_mastery),
            selectinload(User.interaction_logs)
        )
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")


    # Serialize the data
    skill_mastery_data = [
        {
            "skill_id": sm.skill_id, 
            "mastery_level": sm.mastery_level,
            "consecutive_errors": sm.consecutive_errors # Expose the efficient counter
        }
        for sm in user.skill_mastery
    ]
    
    interaction_log_data = [
        {
            "timestamp": log.timestamp.isoformat(),
            "question_id": log.question_id,
            "skill": log.skill,
            "user_answer": log.user_answer,
            "is_correct": log.is_correct,
            "time_taken_ms": log.time_taken_ms,
            "hint_shown": log.hint_shown,
            "hint_style_used": log.hint_style_used,
            "user_feedback_rating": log.user_feedback_rating,
            "bkt_change": log.bkt_change,
        }
        for log in sorted(user.interaction_logs, key=lambda x: x.timestamp, reverse=True)[:20] # Return last 20
    ]

    return {
        "user_id": user.id,
        "created_at": user.created_at.isoformat(),
        "preferences": user.preferences,
        "feedback_scores": user.feedback_scores,
        "skill_mastery": skill_mastery_data,
        "interaction_history": interaction_log_data,
    }
