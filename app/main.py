# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import sys

# Add project root to sys.path to allow for absolute imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import routers and services
from app.endpoints import (
    questions as questions_router,
    answer as answer_router,
    hints as hints_router,
    users as users_router,
    preferences as preferences_router,
    proactive_hints as proactive_hints_router
)
from app.services.pdf_ingestion import ingest_pdf
from app.services.rag_agent import ensure_rag_components_initialized
from app.services.question_service import question_service
from app.utils.config import settings
from app.utils.logger import logger
from app.utils.db import engine
from app.models.user import Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown events.
    """
    logger.info("AI Tutor API starting up...")
    
    # Create database tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    logger.info("Loading questions...")
    question_service.load_questions(settings.QUESTION_CSV_FILE_PATH)
    logger.info(f"Loaded {len(question_service.get_all_questions())} questions.")
    logger.info(f"Found {len(question_service.get_all_skills())} unique skills: {question_service.get_all_skills()}")

    # --- PDF Ingestion Logic ---
    # This will now be called correctly on startup. The function itself
    # is responsible for checking if ingestion is actually needed.
    logger.info("Checking for PDF ingestion...")
    ingest_pdf()

    # Initialize RAG components after ingestion is confirmed
    logger.info("Initializing RAG components...")
    try:
        ensure_rag_components_initialized()
    except Exception as e:
        logger.critical(f"Fatal error during RAG initialization: {e}")
        sys.exit(1) # Exit if RAG fails, as the app is not functional
    
    logger.info("Startup complete.")
    yield
    # On shutdown
    logger.info("AI Tutor API shutting down...")

# --- FastAPI App Initialization ---
app = FastAPI(
    title="AI Tutor API",
    description="API for a personalized AI-powered tutor.",
    version="0.7.0",
    lifespan=lifespan
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Routers ---
app.include_router(questions_router.router, prefix="/questions", tags=["Questions"])
app.include_router(answer_router.router, prefix="/answer", tags=["Answers"])
app.include_router(hints_router.router, prefix="/hints", tags=["Hints"])
app.include_router(users_router.router, prefix="/users", tags=["Users"])
# The prefix for preferences is defined within its own router to include the user_id path parameter
app.include_router(preferences_router.router) 
app.include_router(proactive_hints_router.router)

# --- Root Endpoint ---
@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API"}
