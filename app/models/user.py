# Data model for user profiles, including login, personalization preferences, and prior knowledge
from pydantic import BaseModel

class User(BaseModel):
    username: str
    password: str  # Note: For POC, plain text is acceptable; do NOT use this approach in production.
    preferred_hint_style: str = "Worked Example"  # Default value; could be "Analogy" or "Leading Question"
    prior_knowledge: str = "Beginner"