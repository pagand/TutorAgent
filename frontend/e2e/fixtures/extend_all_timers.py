"""
frontend/e2e/fixtures/extend_all_timers.py

Exercises the same bulk timer extension the admin UI's "Exam Control" section
calls — imports EXTEND_ALL_TIMERS_SQL from app/admin/queries.py so the two
paths can't drift apart, but runs it through the async engine already used
by this E2E fixture ecosystem (see expire_session.py) rather than going
through the admin router.

Usage:
    DATABASE_URL=postgresql+asyncpg://<user>@localhost:5432/aitutor_e2e_db \
        python frontend/e2e/fixtures/extend_all_timers.py <extra_minutes>
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from sqlalchemy import text
from app.utils.db import AsyncSessionLocal
from app.admin.queries import EXTEND_ALL_TIMERS_SQL


async def run(extra_minutes: int) -> int:
    extra_ms = extra_minutes * 60 * 1000
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(EXTEND_ALL_TIMERS_SQL), {"extra": extra_ms})
        await session.commit()
        return result.rowcount


if __name__ == "__main__":
    extra_minutes = int(sys.argv[1])
    affected = asyncio.run(run(extra_minutes))
    print(f"Extended {affected} unsubmitted session(s) by {extra_minutes} minute(s).")
