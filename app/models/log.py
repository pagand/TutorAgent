# Data model for user interaction logs (timestamps, actions, hint requests, responses, etc.)
# app/models/log.py
from pydantic import BaseModel
from datetime import datetime
from typing import Dict

class LogEntry(BaseModel):
    timestamp: datetime
    user_id: str
    question_id: int
    skill: str
    action: str # e.g., "answered", "requested_hint"
    user_answer: str | None = None
    is_correct: bool | None = None
    time_taken_ms: int | None = None
    details: Dict | None = None # For extra info like hint provided

