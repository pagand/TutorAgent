# app/services/personalization_service.py
import random
from app.models.user import User
from app.models.enums import HintStyle
from app.state_manager import get_user_state
from app.utils.logger import logger
from app.utils.config import settings
from collections import defaultdict

class PersonalizationService:
    def get_user_preferences(self, user_id: str) -> dict:
        """Gets user preferences, returning defaults if not set."""
        state = get_user_state(user_id)
        if "preferences" not in state:
            state["preferences"] = User(username=user_id, password="").dict()
        return state["preferences"]

    def update_user_preferences(self, user_id: str, preferences_update: dict) -> dict:
        """Updates user preferences."""
        state = get_user_state(user_id)
        if "preferences" not in state:
            self.get_user_preferences(user_id)
        state["preferences"].update(preferences_update)
        logger.info(f"Updated preferences for user {user_id}: {preferences_update}")
        return state["preferences"]

    def get_adaptive_hint_style(self, user_id: str) -> str:
        """
        Determines the best hint style for a user using an epsilon-greedy strategy.
        """
        preferences = self.get_user_preferences(user_id)
        preferred_style = HintStyle(preferences.get("preferred_hint_style", HintStyle.AUTOMATIC))

        # If the user has explicitly chosen a style, respect it
        if preferred_style != HintStyle.AUTOMATIC:
            logger.debug(f"User {user_id} has explicit preference: {preferred_style.value}")
            return preferred_style.value

        # Epsilon-greedy exploration
        if random.random() < settings.exploration_rate:
            # Explore: choose a random style
            available_styles = [s.value for s in HintStyle if s != HintStyle.AUTOMATIC]
            chosen_style = random.choice(available_styles)
            logger.info(f"Adaptive selection for user {user_id}: Exploring with random style '{chosen_style}'.")
            return chosen_style

        # Exploit: choose the best-rated style
        state = get_user_state(user_id)
        feedback_scores = state.get("feedback_scores", {})
        if not feedback_scores:
            # If no feedback yet, default to a safe choice
            logger.debug(f"No feedback scores for user {user_id}. Defaulting to Conceptual.")
            return HintStyle.CONCEPTUAL.value

        # Calculate average rating for each style
        average_ratings = {
            style: data["total_rating"] / data["count"]
            for style, data in feedback_scores.items() if data["count"] > 0
        }

        if not average_ratings:
            logger.debug(f"No ratings yet for user {user_id}. Defaulting to Conceptual.")
            return HintStyle.CONCEPTUAL.value

        # Find the style with the highest average rating
        best_style = max(average_ratings, key=average_ratings.get)
        logger.info(f"Adaptive selection for user {user_id}: Exploiting best style '{best_style}'.")
        return best_style

    def record_feedback(self, user_id: str, hint_style: str, rating: int, bkt_change: float = 0.0):
        """
        Records user feedback and BKT change for a given hint style.
        The effectiveness score is a weighted average of the rating and BKT improvement.
        """
        state = get_user_state(user_id)
        if "feedback_scores" not in state:
            state["feedback_scores"] = defaultdict(lambda: {"total_rating": 0, "count": 0})

        # Normalize rating (1-5 scale to 0-1 scale)
        normalized_rating = (rating - 1) / 4

        # Combine feedback
        feedback_weight = settings.feedback_rating_weight
        bkt_weight = 1 - feedback_weight
        combined_score = (feedback_weight * normalized_rating) + (bkt_weight * bkt_change)

        feedback_scores = state["feedback_scores"][hint_style]
        feedback_scores["total_rating"] += combined_score
        feedback_scores["count"] += 1
        
        logger.info(f"Recorded feedback for user {user_id}: Style='{hint_style}', Rating={rating}, BKT Change={bkt_change:.4f}. New average score: {feedback_scores['total_rating'] / feedback_scores['count']:.4f}")

personalization_service = PersonalizationService()
