# tests/conftest.py
# Shared fixtures for all tests.
# Uses SQLite in-memory DB so tests run without a live PostgreSQL instance.
# LLM/RAG components are mocked to avoid network/model dependencies.
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from httpx import AsyncClient, ASGITransport

from app.models.user import Base
from app.utils.db import get_db

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    async_session_factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """
    FastAPI test client with:
    - DB overridden to in-memory SQLite
    - App lifespan startup mocked (no PDF ingestion, no RAG init, no question CSV)
    - LLM client mocked
    """
    async def override_get_db():
        yield db_session

    # Minimal question mock so endpoints that look up questions don't fail
    mock_question = MagicMock()
    mock_question.question_number = 1
    mock_question.question = "Which OSI layer handles logical addressing?"
    mock_question.options = ["Transport", "Network", "Data Link", "Application"]
    mock_question.correct_answer = "2"
    mock_question.question_type = "multiple_choice"
    mock_question.skill = "Networking"

    mock_llm = AsyncMock()
    mock_llm_response = MagicMock()
    mock_llm_response.content = "Think about which layer uses IP addresses."
    mock_llm.__or__ = MagicMock(return_value=mock_llm)  # support pipe operator
    mock_llm.ainvoke = AsyncMock(return_value="Think about which layer uses IP addresses.")

    mock_retriever = AsyncMock()
    mock_retriever.ainvoke = AsyncMock(return_value=[])

    with (
        patch("app.services.rag_agent.ensure_rag_components_initialized", return_value=None),
        patch("app.services.pdf_ingestion.ingest_pdf", return_value=None),
        patch("app.services.question_service.question_service.load_questions", return_value=None),
        patch("app.services.question_service.question_service.get_question_by_id", return_value=mock_question),
        patch("app.services.question_service.question_service.get_all_questions", return_value=[mock_question]),
        patch("app.services.question_service.question_service.get_all_skills", return_value=["Networking"]),
        patch("app.services.rag_agent._llm_client", mock_llm),
        patch("app.services.rag_agent._retriever", mock_retriever),
        patch("app.endpoints.chat._llm_client", mock_llm),
        patch("app.endpoints.chat._retriever", mock_retriever),
    ):
        from app.main import app
        app.dependency_overrides[get_db] = override_get_db
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()
