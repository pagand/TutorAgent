"""
Tests for prod/seed_participants.py (Stage 5).

Covers the properties that matter for running this on every EC2 boot,
including mid-exam reboots:
- idempotent re-run: a second run against an unchanged manifest changes nothing
- in-flight state survives a re-seed: status, active_session_id, started_at
  and last_seen_at on an existing row are never overwritten
- a group/intervention change in the manifest propagates to an existing row
- new rows are inserted with status="unused"
"""
import csv
import os
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy.future import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "prod")))
import seed_participants  # noqa: E402

from app.models.user import Participant


def _write_manifest(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["token", "name", "identifier", "group", "intervention"])
        writer.writeheader()
        writer.writerows(rows)


async def _seed(db_session, monkeypatch, tmp_path, rows):
    manifest_path = tmp_path / "manifest.csv"
    _write_manifest(manifest_path, rows)
    monkeypatch.setattr(seed_participants, "MANIFEST_PATH", str(manifest_path))

    class _SessionCtx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(seed_participants, "AsyncSessionLocal", lambda: _SessionCtx())
    await seed_participants.run()


@pytest.mark.asyncio
async def test_inserts_new_participant_as_unused(db_session, monkeypatch, tmp_path):
    await _seed(db_session, monkeypatch, tmp_path, [
        {"token": "TOK1", "name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive"},
    ])

    result = await db_session.execute(select(Participant).filter_by(token="TOK1"))
    p = result.scalars().first()
    assert p is not None
    assert p.status == "unused"
    assert p.name == "Alice"
    assert p.group == "adaptive"


@pytest.mark.asyncio
async def test_idempotent_rerun_changes_nothing(db_session, monkeypatch, tmp_path):
    rows = [{"token": "TOK1", "name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive"}]
    await _seed(db_session, monkeypatch, tmp_path, rows)
    await _seed(db_session, monkeypatch, tmp_path, rows)

    result = await db_session.execute(select(Participant))
    all_rows = result.scalars().all()
    assert len(all_rows) == 1
    assert all_rows[0].status == "unused"


@pytest.mark.asyncio
async def test_reseed_preserves_in_flight_session_state(db_session, monkeypatch, tmp_path):
    rows = [{"token": "TOK1", "name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive"}]
    await _seed(db_session, monkeypatch, tmp_path, rows)

    result = await db_session.execute(select(Participant).filter_by(token="TOK1"))
    p = result.scalars().first()
    p.status = "active"
    p.active_session_id = "sess_live"
    started = datetime.now(timezone.utc)
    p.started_at = started
    p.last_seen_at = started
    await db_session.commit()

    # Re-run the same manifest, simulating a reboot mid-exam
    await _seed(db_session, monkeypatch, tmp_path, rows)

    result = await db_session.execute(select(Participant).filter_by(token="TOK1"))
    p = result.scalars().first()
    assert p.status == "active"
    assert p.active_session_id == "sess_live"
    assert p.started_at is not None
    assert p.last_seen_at is not None


@pytest.mark.asyncio
async def test_reseed_updates_group_and_intervention(db_session, monkeypatch, tmp_path):
    await _seed(db_session, monkeypatch, tmp_path, [
        {"token": "TOK1", "name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive"},
    ])
    await _seed(db_session, monkeypatch, tmp_path, [
        {"token": "TOK1", "name": "Alice", "identifier": "a1", "group": "free_choice", "intervention": "manual"},
    ])

    result = await db_session.execute(select(Participant).filter_by(token="TOK1"))
    p = result.scalars().first()
    assert p.group == "free_choice"
    assert p.intervention == "manual"


@pytest.mark.asyncio
async def test_missing_manifest_exits_nonzero(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(seed_participants, "MANIFEST_PATH", str(tmp_path / "does_not_exist.csv"))
    with pytest.raises(SystemExit) as exc_info:
        await seed_participants.run()
    assert exc_info.value.code != 0


@pytest.mark.asyncio
async def test_empty_manifest_exits_nonzero(db_session, monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest.csv"
    _write_manifest(manifest_path, [])
    monkeypatch.setattr(seed_participants, "MANIFEST_PATH", str(manifest_path))
    with pytest.raises(SystemExit) as exc_info:
        await seed_participants.run()
    assert exc_info.value.code != 0
