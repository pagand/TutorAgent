# Data model for user interaction logs (timestamps, actions, hint requests, responses, etc.)
# app/models/log.py
from pydantic import BaseModel
from datetime import datetime

class UserLog(BaseModel):
    user_id: str
    timestamp: datetime
    action: str
    details: dict
