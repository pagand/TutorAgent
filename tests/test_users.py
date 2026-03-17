# tests/test_users.py
# Tests for user creation, A/B group assignment, and profile retrieval.
import pytest


async def test_create_user_returns_profile(client):
    """POST /users/ should create a user and return their profile."""
    response = await client.post("/users/", json={"user_id": "student_01"})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "student_01"
    assert "preferences" in data
    assert "ab_group" in data["preferences"]
    assert data["preferences"]["ab_group"] in ("adaptive", "free_choice")


async def test_create_user_idempotent(client):
    """Calling POST /users/ twice with the same ID should return the same user."""
    await client.post("/users/", json={"user_id": "student_02"})
    response = await client.post("/users/", json={"user_id": "student_02"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "student_02"


async def test_get_user_profile(client):
    """GET /users/{user_id}/profile should return full profile after creation."""
    await client.post("/users/", json={"user_id": "student_03"})
    response = await client.get("/users/student_03/profile")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "student_03"
    assert "skill_mastery" in data
    assert "interaction_history" in data


async def test_get_nonexistent_user_profile_returns_404(client):
    response = await client.get("/users/nonexistent_xyz/profile")
    assert response.status_code == 404


async def test_ab_group_set_on_first_create_not_overwritten(client):
    """A/B group should be set at creation and not changed on subsequent calls."""
    await client.post("/users/", json={"user_id": "student_ab"})
    profile1 = await client.get("/users/student_ab/profile")
    group1 = profile1.json()["preferences"]["ab_group"]

    # Create again (idempotent)
    await client.post("/users/", json={"user_id": "student_ab"})
    profile2 = await client.get("/users/student_ab/profile")
    group2 = profile2.json()["preferences"]["ab_group"]

    assert group1 == group2


async def test_intervention_preference_defaults_to_proactive(client):
    """New users should default to proactive intervention so timer polling is active."""
    response = await client.post("/users/", json={"user_id": "student_proa"})
    prefs = response.json()["preferences"]
    assert prefs.get("intervention_preference") == "proactive"
