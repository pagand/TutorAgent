"""
frontend/e2e/fixtures/seed_participants.py

Seeds the fixed Participant tokens used by the Playwright E2E suite (Stage 1b).
Modeled directly on prod/generate_tokens.py's upsert pattern, but hardcoded
(no CSV, no manifest file) since these are fixture identities, not real students.

Run against the dedicated E2E database, never the normal dev DB:
    DATABASE_URL=postgresql+asyncpg://<user>@localhost:5432/aitutor_e2e_db \
        python frontend/e2e/fixtures/seed_participants.py

Called automatically by Playwright's globalSetup before the suite runs.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from sqlalchemy import delete
from sqlalchemy.future import select
from app.models.user import (
    Participant, User, ExamSession, InteractionLog, SkillMastery,
    UserActionLog, ChatLog, InterventionLog,
)
from app.utils.db import AsyncSessionLocal

FIXTURE_PARTICIPANTS = [
    {"token": "E2ECRITPATH", "name": "E2E Critical Path", "identifier": "e2e-critpath", "group": "free_choice", "intervention": "manual"},
    {"token": "E2ERELOAD", "name": "E2E Reload Recovery", "identifier": "e2e-reload", "group": "free_choice", "intervention": "manual"},
    {"token": "E2EOUTAGE", "name": "E2E Outage Resume", "identifier": "e2e-outage", "group": "free_choice", "intervention": "manual"},
    {"token": "E2ELOCK", "name": "E2E Second Device Lock", "identifier": "e2e-lock", "group": "free_choice", "intervention": "manual"},
    {"token": "E2ETIMER", "name": "E2E Timer Expiry", "identifier": "e2e-timer", "group": "free_choice", "intervention": "manual"},
]


async def run():
    async with AsyncSessionLocal() as session:
        for row in FIXTURE_PARTICIPANTS:
            token = row["token"]

            # Wipe any interaction/session data left over from a previous suite
            # run, so every run starts each fixture token from a clean slate.
            await session.execute(delete(InteractionLog).where(InteractionLog.user_id == token))
            await session.execute(delete(SkillMastery).where(SkillMastery.user_id == token))
            await session.execute(delete(UserActionLog).where(UserActionLog.user_id == token))
            await session.execute(delete(ChatLog).where(ChatLog.user_id == token))
            await session.execute(delete(InterventionLog).where(InterventionLog.user_id == token))
            await session.execute(delete(ExamSession).where(ExamSession.user_id == token))
            await session.execute(delete(User).where(User.id == token))

            result = await session.execute(select(Participant).filter_by(identifier=row["identifier"]))
            participant = result.scalars().first()
            if participant:
                participant.token = token
                participant.group = row["group"]
                participant.intervention = row["intervention"]
                participant.name = row["name"]
                participant.status = "unused"
                participant.active_session_id = None
                participant.last_seen_at = None
                participant.started_at = None
            else:
                session.add(Participant(
                    token=token,
                    name=row["name"],
                    identifier=row["identifier"],
                    group=row["group"],
                    intervention=row["intervention"],
                    status="unused",
                ))
        await session.commit()
    print(f"Seeded {len(FIXTURE_PARTICIPANTS)} E2E participant(s).")


if __name__ == "__main__":
    asyncio.run(run())
