# app/services/personalization_service.py
from app.models.user import User
from app.state_manager import get_user_state
from app.utils.logger import logger
from collections import defaultdict

class PersonalizationService:
    def get_user_preferences(self, user_id: str) -> dict:
        """Gets user preferences, returning defaults if not set."""
        state = get_user_state(user_id)
        if "preferences" not in state:
            # Initialize with default User model
            state["preferences"] = User(username=user_id, password="").dict()
        return state["preferences"]

    def update_user_preferences(self, user_id: str, preferences_update: dict) -> dict:
        """Updates user preferences."""
        state = get_user_state(user_id)
        # Ensure preferences are initialized before updating
        if "preferences" not in state:
            self.get_user_preferences(user_id)
        
        # Update the existing preferences dictionary
        state["preferences"].update(preferences_update)
        logger.info(f"Updated preferences for user {user_id}: {preferences_update}")
        return state["preferences"]

    def get_adaptive_hint_style(self, user_id: str) -> str:
        """
        Determines the best hint style for a user.
        For now, it returns the user's explicit preference.
        This is the hook for future adaptive logic.
        """
        preferences = self.get_user_preferences(user_id)
        # Future logic will go here. For now, just respect the user's setting.
        return preferences.get("preferred_hint_style", "Worked Example")

    def record_feedback(self, user_id: str, hint_style: str, rating: int):
        """
        Records user feedback for a given hint style and updates effectiveness scores.
        A simple moving average is used to track effectiveness.
        """
        state = get_user_state(user_id)
        if "feedback_scores" not in state:
            state["feedback_scores"] = defaultdict(lambda: {"total_rating": 0, "count": 0})

        feedback_scores = state["feedback_scores"][hint_style]
        feedback_scores["total_rating"] += rating
        feedback_scores["count"] += 1
        
        logger.info(f"Recorded feedback for user {user_id}: Style='{hint_style}', Rating={rating}. New average: {feedback_scores['total_rating'] / feedback_scores['count']:.2f}")

personalization_service = PersonalizationService()
