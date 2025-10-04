# app/models/user.py
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    Text,
    Boolean,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
from app.utils.config import settings


Base = declarative_base()



class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Preferences, etc. can be added here
    preferences = Column(JSON, default=lambda: {"preferred_hint_style": "Automatic", "feedback_preference": "immediate"})
    feedback_scores = Column(JSON, default=lambda: {})

    # Relationships
    skill_mastery = relationship("SkillMastery", back_populates="user")
    interaction_logs = relationship("InteractionLog", back_populates="user")


class SkillMastery(Base):
    __tablename__ = "skill_mastery"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    skill_id = Column(String, index=True)
    mastery_level = Column(Float, default=settings.bkt_p_l0)
    consecutive_errors = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="skill_mastery")


class InteractionLog(Base):
    __tablename__ = "interaction_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    question_id = Column(Integer)
    skill = Column(String)
    
    # Answer details
    user_answer = Column(Text, nullable=True)
    is_correct = Column(Boolean, nullable=True)
    time_taken_ms = Column(Integer, nullable=True)

    # Hint and feedback details (for a single interaction loop)
    hint_shown = Column(Boolean, default=False)
    hint_style_used = Column(String, nullable=True)
    hint_text = Column(Text, nullable=True) # <-- ADDED
    user_feedback_rating = Column(Integer, nullable=True) # e.g., 1-5
    
    # Performance metrics
    bkt_change = Column(Float, nullable=True)

    # Relationship
    user = relationship("User", back_populates="interaction_logs")
