# tests/test_llm_switching.py
import pytest
import os
from fastapi.testclient import TestClient
from app.utils.config import settings # To read the configured provider for the integration test
from app.utils.logger import logger

# This fixture ensures ChromaDB is set up before these tests run
@pytest.mark.usefixtures("setup_test_chromadb")
class TestLLMIntegration:

    # Test using the default mock LLM applied by the auto-mock fixture
    @pytest.mark.stage2
    def test_hint_uses_mock_by_default(self, client: TestClient, monkeypatch):
        """Verify hint generation uses the mocked LLM by default."""
        logger.info("Testing default LLM mock...")
        
        # Mock the get_rag_hint function to return a specific value
        async def mock_get_rag_hint(*args, **kwargs):
            return {
                "hint": "mocked hint from the auto-mock fixture",
                "hint_style": "mock_style"
            }

        monkeypatch.setattr("app.endpoints.hints.rag_agent.get_rag_hint", mock_get_rag_hint)

        response = client.post("/hints/", json={"user_id": "llm_mock_user", "question_number": 1})
        assert response.status_code == 200
        data = response.json()
        logger.info(f"Received hint: {data['hint']}")
        assert "mocked hint from the auto-mock fixture" in data["hint"]
        logger.info("Default LLM mock test passed.")


    # Single test to hit the REAL configured LLM provider
    @pytest.mark.stage5 # This tests final integration
    @pytest.mark.llm_integration # Custom marker to enable this test selectively
    # Skip if the required API key isn't set OR if Ollama isn't the provider (adjust as needed)
    @pytest.mark.skipif(
        (settings.llm_provider == "openai" and not os.getenv("OPENAI_API_KEY")) or \
        (settings.llm_provider == "google" and not os.getenv("GOOGLE_API_KEY")),
        # Add check for Ollama reachability if desired, or assume it runs if selected
        # Add Bedrock checks if needed
        reason="Requires API Key for configured cloud provider in .env OR Ollama configured"
    )
    def test_hint_with_real_configured_llm(self, client: TestClient):
        """
        Test hitting the ACTUAL LLM configured via settings (from .env).
        Verifies connectivity and auth for the chosen provider.
        """
        configured_provider = settings.llm_provider
        logger.info(f"Testing REAL LLM integration for provider: {configured_provider}...")

        # No monkeypatching here - the mock fixture skips itself due to the 'llm_integration' mark

        response = client.post("/hints/", json={
            "user_id": "llm_real_user",
            "question_number": 1, # Use a question likely to have context
            "user_answer": "An incorrect answer to get context"
        })

        # Check for success, but be mindful that LLMs can sometimes fail temporarily
        if response.status_code != 200:
             logger.error(f"Real LLM ({configured_provider}) request failed: {response.status_code} - {response.text}")
             pytest.fail(f"Real LLM ({configured_provider}) request failed.")

        assert response.status_code == 200
        data = response.json()
        hint = data.get("hint", "")
        logger.info(f"Received hint from real {configured_provider}: {hint[:100]}...")

        assert isinstance(hint, str)
        assert len(hint) > 5 # Check for a plausible hint length
        assert "mocked hint" not in hint # Verify it's not the mock response
        # Cannot assert exact content, just that it seems like a real response
        logger.info(f"Real LLM integration test for provider '{configured_provider}' passed.")