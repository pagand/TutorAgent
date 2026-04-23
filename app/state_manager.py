# app/state_manager.py
import random
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.user import User, SkillMastery, InteractionLog
from app.utils.db import AsyncSessionLocal
from app.utils.logger import logger
from datetime import datetime
from app.utils.config import settings
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.question_service import question_service



async def get_user_or_create(session: AsyncSession, user_id: str) -> User:
    """
    Fetches a user from the DB or creates a new one and adds it to the session.
    The calling function is responsible for committing the transaction.
    """
    result = await session.execute(select(User).filter_by(id=user_id))
    user = result.scalars().first()
    if not user:
        ab_group = random.choice(["adaptive", "free_choice"])
        logger.info(f"Adding new user '{user_id}' to session. A/B group: {ab_group}")
        user = User(
            id=user_id,
            preferences={
                "hint_style_preference": "adaptive",
                "intervention_preference": "proactive",
                "ab_group": ab_group,
            }
        )
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
    
    sorted_logs = sorted(user.interaction_logs, key=lambda x: x.timestamp)
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
        for log in sorted_logs
    ]

    # Build completed_answers: correct answers revealed only for fully-attempted questions
    # (correct or 2+ wrong attempts). Safe to expose — exam is over for those questions.
    logs_by_question: dict[int, list] = {}
    for log in sorted_logs:
        logs_by_question.setdefault(log.question_id, []).append(log)

    completed_answers: dict[int, str] = {}
    for qid, logs in logs_by_question.items():
        real_attempts = [l for l in logs if l.user_answer is not None]
        any_correct = any(l.is_correct for l in real_attempts)
        if any_correct or len(real_attempts) >= 2:
            q = question_service.get_question_by_id(qid)
            if q:
                completed_answers[qid] = str(q.correct_answer)

    return {
        "user_id": user.id,
        "created_at": user.created_at.isoformat(),
        "preferences": user.preferences,
        "feedback_scores": user.feedback_scores,
        "skill_mastery": skill_mastery_data,
        "interaction_history": interaction_log_data,
        "completed_answers": completed_answers,
    }

async def delete_user_by_id(session: AsyncSession, user_id: str) -> bool:
    """Deletes a user and all their associated data from the database."""
    logger.debug(f"Attempting to delete user: {user_id}")
    result = await session.execute(select(User).filter_by(id=user_id))
    user = result.scalars().first()
    
    if not user:
        logger.warning(f"User '{user_id}' not found for deletion.")
        return False
        
    await session.delete(user)
    await session.commit()
    logger.info(f"Successfully deleted user '{user_id}'.")
    return True
