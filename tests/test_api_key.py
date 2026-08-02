# tests/test_api_key.py
# Tests for the X-API-Key middleware (Stage 2). Monkeypatches app.utils.config.settings.api_key
# per test — the middleware reads it per-request, not at import time, so this works without
# reconstructing the app or client.
from app.utils.config import settings


async def test_no_api_key_configured_passes_through(client, monkeypatch):
    """Default state (unset API_KEY): requests succeed with no header — dev/E2E must be unaffected."""
    monkeypatch.setattr(settings, "api_key", None)
    response = await client.get("/questions/")
    assert response.status_code == 200


async def test_missing_header_rejected_when_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.get("/questions/")
    assert response.status_code == 401


async def test_wrong_header_rejected_when_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.get("/questions/", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


async def test_non_ascii_header_rejected_not_500(client, monkeypatch):
    """hmac.compare_digest raises TypeError on a str with non-ASCII chars unless both
    sides are compared as bytes — this must come back as a clean 401, not a 500.
    httpx's client-side header encoding rejects non-ASCII str values outright (it enforces
    ASCII before the request ever leaves the client), so the raw UTF-8 bytes are passed
    directly to bypass that client-side guardrail and reach the server code being tested."""
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.get("/questions/", headers={"X-API-Key": "café-not-the-key".encode("utf-8")})
    assert response.status_code == 401


async def test_401_still_carries_cors_headers(client, monkeypatch):
    """Middleware must be registered before CORSMiddleware so a rejection still gets CORS
    headers — otherwise a browser reports a CORS failure instead of the real 401."""
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.get("/questions/", headers={"Origin": "https://example.com"})
    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") is not None


async def test_correct_header_accepted_when_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.get("/questions/", headers={"X-API-Key": "stage2-secret"})
    assert response.status_code == 200


async def test_root_exempt_even_with_key_configured(client, monkeypatch):
    """GET / must stay reachable with no header — docker-compose's healthcheck and nginx's /health hit it bare."""
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.get("/")
    assert response.status_code == 200


async def test_options_preflight_exempt_when_key_configured(client, monkeypatch):
    """CORS preflights can't carry custom headers — must never be rejected by the key check."""
    monkeypatch.setattr(settings, "api_key", "stage2-secret")
    response = await client.options("/questions/", headers={
        "Origin": "https://example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert response.status_code == 200
