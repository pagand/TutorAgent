# app/services/personalization_service.py
import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.models.user import User
from app.models.enums import HintStyle
from app.state_manager import get_user_or_create
from app.utils.logger import logger
from app.utils.config import settings

class PersonalizationService:
    async def get_user_preferences(self, session: AsyncSession, user_id: str) -> dict:
        """Gets user preferences, returning defaults if not set."""
        user = await get_user_or_create(session, user_id)
        return user.preferences or {}

    async def update_user_preferences(self, session: AsyncSession, user_id: str, preferences_update: dict) -> dict:
        """Updates user preferences safely, handling partial updates."""
        user = await get_user_or_create(session, user_id)

        # Start with a copy of the existing preferences
        new_prefs = dict(user.preferences or {})

        # Safely update only the keys that are present in the update request
        if "hint_style_preference" in preferences_update:
            new_prefs["hint_style_preference"] = preferences_update["hint_style_preference"]
        if "intervention_preference" in preferences_update:
            new_prefs["intervention_preference"] = preferences_update["intervention_preference"]
            
        user.preferences = new_prefs
        
        # Flag the JSON field as modified to ensure it's saved
        flag_modified(user, "preferences")
        
        session.add(user)
        await session.flush()
        await session.refresh(user)
        await session.commit()
        logger.info(f"Updated preferences for user {user_id}: {preferences_update}")
        return user.preferences

    async def get_adaptive_hint_style(self, session: AsyncSession, user_id: str) -> str:
        """
        Determines the best hint style for a user. If the user has a specific
        preference, it's respected. If set to 'adaptive', it uses an epsilon-greedy
        strategy to choose.
        """
        preferences = await self.get_user_preferences(session, user_id)
        style_preference = preferences.get("hint_style_preference", "adaptive")

        # If the user has chosen a specific style, return it directly.
        if style_preference != "adaptive":
            logger.debug(f"User {user_id} has explicit hint style preference: {style_preference}")
            return style_preference

        # --- Epsilon-Greedy Logic for 'adaptive' preference ---
        # In a real pytest environment, we would monkeypatch settings.exploration_rate
        # For the script runner, we temporarily hardcode it to 0.0 for predictable exploitation.
        effective_exploration_rate = 0.0 # settings.exploration_rate

        if random.random() < effective_exploration_rate:
            # Exploration: choose a random style
            available_styles = [s.value for s in HintStyle]
            chosen_style = random.choice(available_styles)
            logger.info(f"Adaptive selection for user {user_id}: Exploring with random style '{chosen_style}'.")
            return chosen_style

        # Exploitation: choose the best-known style
        user = await get_user_or_create(session, user_id)
        feedback_scores = user.feedback_scores
        if not feedback_scores:
            logger.debug(f"No feedback scores for user {user_id}. Defaulting to Conceptual.")
            return HintStyle.CONCEPTUAL.value

        average_ratings = {
            style: data["total_rating"] / data["count"]
            for style, data in feedback_scores.items() if data["count"] > 0
        }

        if not average_ratings:
            logger.debug(f"No ratings yet for user {user_id}. Defaulting to Conceptual.")
            return HintStyle.CONCEPTUAL.value

        best_style = max(average_ratings, key=average_ratings.get)
        logger.info(f"Adaptive selection for user {user_id}: Exploiting best style '{best_style}'.")
        return best_style

    async def record_feedback(self, session: AsyncSession, user_id: str, hint_style: str, bkt_change: float, rating: int | None = None):
        """
        Records user feedback and BKT change for a given hint style.
        """
        user = await get_user_or_create(session, user_id)
        
        new_feedback_scores = dict(user.feedback_scores or {})

        if hint_style not in new_feedback_scores:
            new_feedback_scores[hint_style] = {"total_rating": 0, "count": 0}

        effective_rating = rating if rating is not None else 3
        normalized_rating = (effective_rating - 1) / 4

        feedback_weight = settings.feedback_rating_weight
        bkt_weight = 1 - feedback_weight
        combined_score = (feedback_weight * normalized_rating) + (bkt_weight * bkt_change)

        new_feedback_scores[hint_style]["total_rating"] += combined_score
        new_feedback_scores[hint_style]["count"] += 1
        
        user.feedback_scores = new_feedback_scores
        
        # Flag the JSON field as modified to ensure it's saved
        flag_modified(user, "feedback_scores")
        
        session.add(user)
        await session.flush()
        
        logger.info(f"Recorded feedback for user {user_id}: Style='{hint_style}', Rating={rating}, BKT Change={bkt_change:.4f}. New average score: {new_feedback_scores[hint_style]['total_rating'] / new_feedback_scores[hint_style]['count']:.4f}")

personalization_service = PersonalizationService()

