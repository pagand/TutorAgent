# tests/test_questions.py
"""Tests for GET /questions/ — verifies correct_answer never appears on the wire (Stage 1a)."""


async def test_get_all_questions_excludes_correct_answer(client):
    res = await client.get("/questions/")
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 1
    assert "correct_answer" not in body[0]


async def test_get_single_question_excludes_correct_answer(client):
    res = await client.get("/questions/1")
    assert res.status_code == 200
    assert "correct_answer" not in res.json()
