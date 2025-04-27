# tests/test_main_app.py
from fastapi.testclient import TestClient
from app.utils.logger import logger # Use app's logger or configure test logger

# pytestmark = pytest.mark.stage1 # Mark whole module if desired

def test_read_root(client: TestClient):
    """Test if the root endpoint returns the welcome message."""
    logger.info("Testing root endpoint...")
    response = client.get("/")
    assert response.status_code == 200
    json_response = response.json()
    assert "message" in json_response
    assert "Welcome to the AI Tutor API" in json_response["message"]
    logger.info("Root endpoint test passed.")