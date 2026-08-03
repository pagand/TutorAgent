# tests/test_llm_quota.py
"""Tests for the in-app LLM spend cap (app/services/llm_quota.py, Stage 4.5).

nginx's rate limit is keyed per source IP and can't see user_id, so it can't
bound cost per account or globally - these are the real ceiling. Exercised
directly against reserve_llm_call rather than through the full /hints/ or
/chat/ endpoints, since those need heavy LLM/RAG mocking that would obscure
what's actually under test here: the counting logic itself.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.user import LlmUsageLog, User
from app.services.llm_quota import GLOBAL_DETAIL, PER_USER_DETAIL, reserve_llm_call
from app.utils.config import settings


async def _create_user(db, user_id: str):
    db.add(User(id=user_id))
    await db.commit()


async def _usage_count(db, user_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(LlmUsageLog).where(LlmUsageLog.user_id == user_id)
    )
    return result.scalar_one()


async def test_per_user_cap_trips_at_exactly_the_limit(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_calls_per_user_per_day", 3)
    monkeypatch.setattr(settings, "llm_max_calls_per_day", 1000)
    await _create_user(db_session, "quota_user_01")

    for _ in range(3):
        await reserve_llm_call(db_session, "quota_user_01", "hint")
        await db_session.commit()

    assert await _usage_count(db_session, "quota_user_01") == 3

    with pytest.raises(HTTPException) as exc:
        await reserve_llm_call(db_session, "quota_user_01", "hint")
    assert exc.value.status_code == 429
    assert exc.value.detail == PER_USER_DETAIL

    # The 4th (rejected) call must not have been recorded.
    assert await _usage_count(db_session, "quota_user_01") == 3


async def test_per_user_cap_does_not_trip_one_below_the_limit(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_calls_per_user_per_day", 3)
    monkeypatch.setattr(settings, "llm_max_calls_per_day", 1000)
    await _create_user(db_session, "quota_user_02")

    for _ in range(2):
        await reserve_llm_call(db_session, "quota_user_02", "chat")
        await db_session.commit()

    # No exception on the call that brings the count to exactly the limit.
    await reserve_llm_call(db_session, "quota_user_02", "chat")
    await db_session.commit()
    assert await _usage_count(db_session, "quota_user_02") == 3


async def test_global_cap_trips_independently_of_per_user_cap(db_session, monkeypatch):
    """Two different users, neither anywhere near their own per-user cap,
    still trip the global ceiling once combined calls reach it."""
    monkeypatch.setattr(settings, "llm_max_calls_per_user_per_day", 1000)
    monkeypatch.setattr(settings, "llm_max_calls_per_day", 2)
    await _create_user(db_session, "quota_global_a")
    await _create_user(db_session, "quota_global_b")

    await reserve_llm_call(db_session, "quota_global_a", "hint")
    await db_session.commit()
    await reserve_llm_call(db_session, "quota_global_b", "hint")
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await reserve_llm_call(db_session, "quota_global_a", "hint")
    assert exc.value.status_code == 429
    assert exc.value.detail == GLOBAL_DETAIL


async def test_reservation_recorded_before_the_llm_call_runs(db_session, monkeypatch):
    """reserve_llm_call is called BEFORE the LLM call in both hints.py and
    chat.py, so a call that then errors out on the Gemini side still counts -
    it can still bill. Simulated here by committing the reservation and
    never calling anything else afterward."""
    monkeypatch.setattr(settings, "llm_max_calls_per_user_per_day", 150)
    monkeypatch.setattr(settings, "llm_max_calls_per_day", 10000)
    await _create_user(db_session, "quota_user_03")

    await reserve_llm_call(db_session, "quota_user_03", "hint")
    await db_session.commit()

    assert await _usage_count(db_session, "quota_user_03") == 1


async def test_calls_outside_the_24h_window_do_not_count(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_calls_per_user_per_day", 1)
    monkeypatch.setattr(settings, "llm_max_calls_per_day", 1000)
    await _create_user(db_session, "quota_user_04")

    stale = LlmUsageLog(
        user_id="quota_user_04", endpoint="hint",
        created_at=datetime.utcnow() - timedelta(hours=25),
    )
    db_session.add(stale)
    await db_session.commit()

    # The cap is 1, and there's already 1 row for this user - but it's
    # outside the rolling 24h window, so this call must still succeed.
    await reserve_llm_call(db_session, "quota_user_04", "hint")
    await db_session.commit()
    assert await _usage_count(db_session, "quota_user_04") == 2
