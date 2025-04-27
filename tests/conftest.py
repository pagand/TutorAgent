# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
import shutil
import os
import logging
from unittest.mock import AsyncMock, MagicMock, patch

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import your FastAPI app instance and state/services
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import settings object directly
from app.utils.config import settings
# Import other necessary components
from app.state_manager import user_states
from app.services.pdf_ingestion import ingest_pdf
# --- Import rag_agent module itself for patching targets ---
from app.services import rag_agent

# --- Define Test Questions Path ---
TEST_QUESTIONS_CSV = "data/test_questions.csv" # Verify this path

mock_llm_instance_session = AsyncMock()
# --- CORRECTED MOCK RETURN VALUE ---
# StrOutputParser expects a string directly from the LLM component
mock_llm_instance_session.ainvoke.return_value = "This is a mocked hint from the SESSION patch."

# --- Fixture to Modify Settings ---
@pytest.fixture(scope="session", autouse=True)
def modify_settings_for_test_questions():
    settings_attribute_name = "QUESTION_CSV_FILE_PATH"
    logger.info(f"Attempting to modify setting '{settings_attribute_name}' to use: {TEST_QUESTIONS_CSV}")
    if not hasattr(settings, settings_attribute_name):
        pytest.fail(f"Settings object does not have attribute '{settings_attribute_name}'. Check app/utils/config.py.")
    if not os.path.exists(TEST_QUESTIONS_CSV):
        pytest.fail(f"Test questions file not found at: {TEST_QUESTIONS_CSV}")
    original_path = getattr(settings, settings_attribute_name)
    try:
        setattr(settings, settings_attribute_name, TEST_QUESTIONS_CSV)
        logger.info(f"Successfully modified setting '{settings_attribute_name}' to '{TEST_QUESTIONS_CSV}' for the session.")
        yield
    finally:
        setattr(settings, settings_attribute_name, original_path)
        logger.info(f"Restored setting '{settings_attribute_name}' to '{original_path}'.")

# --- ADD NEW FIXTURE for Session-Scoped LLM Mocking ---
# Create one shared AsyncMock instance for all patched classes to return
mock_llm_instance_session = AsyncMock()
# Configure the desired return value for the mocked 'ainvoke'
# Use a distinct message to confirm this mock is being used
mock_llm_instance_session.ainvoke.return_value = {"answer": "This is a mocked hint from the SESSION patch."}

@pytest.fixture(scope="session", autouse=True)
def apply_llm_mock_patch_session(request):
    """
    Applies session-wide patches to LLM classes within rag_agent module
    unless the test is marked with 'llm_integration'.
    Uses unittest.mock.patch for session scope compatibility.
    """
    # --- Skip logic remains the same ---
    if "llm_integration" in getattr(request, "keywords", {}):
         logger.warning("Detected 'llm_integration' marker - skipping LLM class patching.")
         yield
         return
    # --- End Skip logic ---

    logger.info("Applying session-wide LLM class patches using unittest.mock.patch.")
    targets_to_patch = [
        "app.services.rag_agent.Ollama",
        "app.services.rag_agent.ChatOpenAI",
        "app.services.rag_agent.ChatGoogleGenerativeAI",
        # Add "app.services.rag_agent.BedrockChat" if used
    ]
    mock_class_factory = MagicMock(return_value=mock_llm_instance_session)

    # --- Store patchers AND their targets ---
    active_patches_info = [] # Store tuples of (target_string, patcher_object)
    # --- End change ---

    for target in targets_to_patch:
        try:
            patcher = patch(target, mock_class_factory)
            patcher.start()
            # --- Store tuple ---
            active_patches_info.append((target, patcher))
            # --- End change ---
            logger.debug(f"Applied session patch to {target}")
        except (AttributeError, ImportError):
            logger.debug(f"Could not apply session patch to {target} - class likely not imported/used directly in rag_agent.")
        except Exception as e:
            logger.error(f"Error applying session patch to {target}: {e}")
            # Stop any already started patches before failing
            for _, p in active_patches_info: p.stop() # Use _ if target not needed here
            pytest.fail(f"Failed to apply session patch to {target}: {e}")

    try:
        yield # Test session runs with patches active
    finally:
        # Stop all patchers in reverse order using the stored info
        for target, patcher in reversed(active_patches_info): # Iterate through stored tuples
            try:
                patcher.stop()
                # --- Use stored target string for logging ---
                logger.debug(f"Stopped session patch for {target}")
                # --- End change ---
            except Exception as e:
                # --- Use stored target string for logging ---
                logger.error(f"Error stopping session patch for {target}: {e}")
                # --- End change ---
        logger.info("Session-wide LLM class patches removed.")

# --- TestClient Fixture ---
@pytest.fixture(scope="session")
def client(modify_settings_for_test_questions, apply_llm_mock_patch_session): # Add dependency
    """
    Creates the TestClient *after* settings have been modified and LLM classes patched.
    """
    # Import app here, after settings are modified AND LLM classes patched
    from app.main import app
    logger.info("Creating TestClient instance for the session (after settings modification and LLM patch).")
    # App startup triggered here will now use the modified settings and patched classes
    with TestClient(app) as c:
        yield c

# --- State Reset Fixture ---
@pytest.fixture(autouse=True)
def reset_user_state():
    user_states.clear()
    yield
    user_states.clear()


# --- ChromaDB Setup/Teardown Fixture ---
TEST_CHROMA_DIR = "./chroma_db/chroma_db_test"
TEST_PDF = "data/test_source_material.pdf"

@pytest.fixture(scope="session", autouse=True)
def setup_test_chromadb(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    original_chroma_dir = settings.chroma_persist_dir # Store original values
    original_pdf_path = settings.pdf_path

    if worker_id == "master" or worker_id == "gw0" or worker_id is None:
        logger.info(f"Setting up test ChromaDB at: {TEST_CHROMA_DIR} (worker: {worker_id})")
        if os.path.exists(TEST_CHROMA_DIR):
            try:
                shutil.rmtree(TEST_CHROMA_DIR)
                logger.info(f"Removed existing test ChromaDB directory: {TEST_CHROMA_DIR}")
            except OSError as e:
                logger.error(f"Error removing directory {TEST_CHROMA_DIR}: {e}")

        settings.chroma_persist_dir = TEST_CHROMA_DIR
        if os.path.exists(TEST_PDF):
            settings.pdf_path = TEST_PDF
            logger.info(f"Using test PDF: {TEST_PDF}")
        else:
            settings.pdf_path = original_pdf_path # Restore if test pdf not found
            logger.warning(f"Test PDF not found at {TEST_PDF}.")
            raise FileNotFoundError(f"Test PDF not found at: {TEST_PDF}")

        try:
            logger.info("Running PDF ingestion for tests...")
            ingest_pdf()
            logger.info("PDF ingestion complete for tests.")
        except Exception as e:
            settings.chroma_persist_dir = original_chroma_dir # Restore on error
            settings.pdf_path = original_pdf_path
            logger.error(f"ERROR during test PDF ingestion: {e}")
            pytest.fail(f"Failed to ingest PDF for tests: {e}")
    else:
        settings.chroma_persist_dir = TEST_CHROMA_DIR
        if os.path.exists(TEST_PDF):
            settings.pdf_path = TEST_PDF

    yield

    if worker_id == "master" or worker_id == "gw0" or worker_id is None:
        logger.info(f"Tearing down test ChromaDB at: {TEST_CHROMA_DIR} (worker: {worker_id})")
        if os.path.exists(TEST_CHROMA_DIR):
            try:
                shutil.rmtree(TEST_CHROMA_DIR)
                logger.info(f"Removed test ChromaDB directory: {TEST_CHROMA_DIR}")
            except OSError as e:
                logger.error(f"Error removing directory {TEST_CHROMA_DIR}: {e}")
        # Restore original settings modified by this fixture
        setattr(settings, 'chroma_persist_dir', original_chroma_dir)
        setattr(settings, 'pdf_path', original_pdf_path)
        logger.info("Restored original ChromaDB and PDF path settings.")