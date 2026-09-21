"""
Tests for prod/generate_tokens.py manifest-load validation (Feature 2:
chat/chatiq experiment flags).

Covers:
- chat=off with chatiq=on is rejected at load time, naming the row number
- the three valid arms (chat off; chat on/chatiq off; chat on/chatiq on) load
- invalid chat/chatiq values are rejected the same way group/intervention are
- accepted rows propagate chat_enabled/chatiq_enabled onto the Participant row
"""
import csv
import os
import sys

import pytest
from sqlalchemy.future import select

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "prod")))
import generate_tokens  # noqa: E402

from app.models.user import Participant


def _write_participants(path, rows, fieldnames=("name", "identifier", "group", "intervention", "chat", "chatiq")):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


async def _run(db_session, monkeypatch, tmp_path, rows, fieldnames=None):
    input_path = tmp_path / "participants.csv"
    output_path = tmp_path / "manifest.csv"
    if fieldnames:
        _write_participants(input_path, rows, fieldnames)
    else:
        _write_participants(input_path, rows)
    monkeypatch.setattr(generate_tokens, "INPUT_PATH", str(input_path))
    monkeypatch.setattr(generate_tokens, "OUTPUT_PATH", str(output_path))

    class _SessionCtx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(generate_tokens, "AsyncSessionLocal", lambda: _SessionCtx())
    await generate_tokens.run()
    return output_path


@pytest.mark.asyncio
async def test_rejects_chat_off_chatiq_on(db_session, monkeypatch, tmp_path, capsys):
    rows = [
        {"name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive",
         "chat": "off", "chatiq": "on"},
    ]
    with pytest.raises(SystemExit) as exc_info:
        await _run(db_session, monkeypatch, tmp_path, rows)
    assert exc_info.value.code != 0
    out = capsys.readouterr().out
    # Row 2 = first data row (header is row 1), matching the existing
    # group/intervention error style.
    assert "row 2" in out
    assert "chat='off'" in out


@pytest.mark.asyncio
async def test_rejects_invalid_chat_value(db_session, monkeypatch, tmp_path):
    rows = [
        {"name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive",
         "chat": "maybe", "chatiq": "off"},
    ]
    with pytest.raises(SystemExit) as exc_info:
        await _run(db_session, monkeypatch, tmp_path, rows)
    assert exc_info.value.code != 0


@pytest.mark.asyncio
async def test_missing_chat_columns_fails_fast(db_session, monkeypatch, tmp_path):
    rows = [
        {"name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive"},
    ]
    with pytest.raises(SystemExit) as exc_info:
        await _run(db_session, monkeypatch, tmp_path, rows,
                    fieldnames=("name", "identifier", "group", "intervention"))
    assert exc_info.value.code != 0


@pytest.mark.asyncio
async def test_accepts_three_valid_arms(db_session, monkeypatch, tmp_path):
    rows = [
        {"name": "Off", "identifier": "arm1", "group": "adaptive", "intervention": "proactive",
         "chat": "off", "chatiq": "off"},
        {"name": "OnNoIQ", "identifier": "arm2", "group": "adaptive", "intervention": "manual",
         "chat": "on", "chatiq": "off"},
        {"name": "OnIQ", "identifier": "arm3", "group": "free_choice", "intervention": "proactive",
         "chat": "on", "chatiq": "on"},
    ]
    await _run(db_session, monkeypatch, tmp_path, rows)

    result = await db_session.execute(select(Participant).order_by(Participant.identifier))
    participants = {p.identifier: p for p in result.scalars().all()}

    assert participants["arm1"].chat_enabled is False
    assert participants["arm1"].chatiq_enabled is False

    assert participants["arm2"].chat_enabled is True
    assert participants["arm2"].chatiq_enabled is False

    assert participants["arm3"].chat_enabled is True
    assert participants["arm3"].chatiq_enabled is True


@pytest.mark.asyncio
async def test_manifest_csv_includes_chat_columns(db_session, monkeypatch, tmp_path):
    rows = [
        {"name": "Alice", "identifier": "a1", "group": "adaptive", "intervention": "proactive",
         "chat": "on", "chatiq": "on"},
    ]
    output_path = await _run(db_session, monkeypatch, tmp_path, rows)

    with open(output_path, newline="") as f:
        manifest_rows = list(csv.DictReader(f))
    assert manifest_rows[0]["chat"] == "on"
    assert manifest_rows[0]["chatiq"] == "on"
