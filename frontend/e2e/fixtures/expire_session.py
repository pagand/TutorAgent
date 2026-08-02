"""
frontend/e2e/fixtures/expire_session.py

Forces an already-started ExamSession into a near-expired state, so the
timer-expiry E2E spec doesn't have to wait out a real 25-minute countdown.
Must be run AFTER the exam has been started for the given user (i.e. after
POST /session/start has created the ExamSession row) — this script only
rewrites exam_start_ms on an existing row, it does not create one.

Usage:
    DATABASE_URL=postgresql+asyncpg://<user>@localhost:5432/aitutor_e2e_db \
        python frontend/e2e/fixtures/expire_session.py <user_id> [seconds_remaining]

seconds_remaining defaults to 3 — enough for the page to render the countdown
and observably tick down to zero within the test's timeout.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from sqlalchemy.future import select
from app.models.user import ExamSession
from app.utils.db import AsyncSessionLocal


async def run(user_id: str, seconds_remaining: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ExamSession).filter_by(user_id=user_id))
        exam_session = result.scalars().first()
        if exam_session is None:
            print(f"ERROR: no ExamSession found for user_id={user_id}. Start the session first.")
            sys.exit(1)

        now_ms = int(time.time() * 1000)
        remaining_ms = seconds_remaining * 1000
        exam_session.exam_start_ms = now_ms - exam_session.exam_duration_ms + remaining_ms
        await session.commit()
    print(f"exam_start_ms rewritten for {user_id}: ~{seconds_remaining}s remaining.")


if __name__ == "__main__":
    user_id = sys.argv[1]
    seconds_remaining = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    asyncio.run(run(user_id, seconds_remaining))
