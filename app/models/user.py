# Data model for user profiles, including login, personalization preferences, and prior knowledge
from pydantic import BaseModel
from app.models.enums import HintStyle

class User(BaseModel):
    username: str
    password: str  # Note: For POC, plain text is acceptable; do NOT use this approach in production.
    preferred_hint_style: HintStyle = HintStyle.AUTOMATIC  # Default to automatic adaptive selection
    feedback_preference: str = "immediate" # Default value; could be "on_demand"
    prior_knowledge: str = "Beginner"