# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
# Import routers
from app.endpoints import questions, hints, answer, users, preferences
# Import services/utils needed at startup
from app.services.pdf_ingestion import ingest_pdf
from app.services.rag_agent import ensure_rag_components_initialized # Import the check function
from app.services.question_service import question_service
from app.utils.config import settings
from app.utils.logger import logger
import sys # Import sys for exit
import os

# --- Global State (Simple approach for POC) ---
# No explicit global needed here now as state_manager handles it internally
# and services are imported directly where needed.

from contextlib import asynccontextmanager
from app.utils.db import engine
from app.models.user import Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup
    logger.info("AI Tutor API starting up...")
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    logger.info("Loading questions...")
    question_service.load_questions(settings.QUESTION_CSV_FILE_PATH)
    logger.info(f"Loaded {len(question_service.get_all_questions())} questions.")
    logger.info(f"Found {len(question_service.get_all_skills())} unique skills: {question_service.get_all_skills()}")

    # Check for PDF and ingest if necessary
    logger.info("Checking for PDF ingestion...")
    if not os.path.exists(settings.chroma_persist_dir) or not os.listdir(settings.chroma_persist_dir):
        logger.info("ChromaDB not found or empty. Ingesting PDF...")
        ingest_pdf()
    else:
        logger.info("Collection 'ai_tutor_collection' already exists and seems populated. Skipping ingestion.")

    # Initialize RAG components
    logger.info("Initializing RAG components...")
    try:
        ensure_rag_components_initialized()
    except Exception as e:
        logger.error(f"Fatal error during RAG initialization: {e}")
        # Depending on the desired behavior, you might want to exit the application
        # For now, we'll log the error and continue, but hint generation will fail.
    
    logger.info("Startup complete. RAG Components initialized.")
    yield
    # On shutdown
    logger.info("AI Tutor API shutting down...")

# --- Rest of main.py remains the same ---
# Initialize FastAPI app with the lifespan manager
app = FastAPI(title="AI Tutor POC - Stage 5.5", lifespan=lifespan)

# --- CORS Middleware ---
# This must be added before the routers are included
origins = [
    "http://localhost:3000", # Default Next.js dev server
    "http://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

from app.endpoints import (
    questions as questions_router,
    answer as answer_router,
    hints as hints_router,
    users as users_router,
    preferences as preferences_router,
    proactive_hints as proactive_hints_router
)
from app.services.rag_agent import ensure_rag_components_initialized
from app.services.question_service import question_service
from app.utils.logger import logger

# --- App Initialization ---
app = FastAPI(
    title="AI Tutor API",
    description="API for a personalized AI-powered tutor.",
    version="0.6.0",
)

# --- Middleware ---
# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Event Handlers ---
@app.on_event("startup")
async def startup_event():
    """
    Application startup logic:
    - Load questions from CSV
    - Initialize RAG components
    """
    logger.info("Application startup...")
    # The init_db() call is removed as Alembic now manages the database schema.
    question_service.load_questions()
    try:
        ensure_rag_components_initialized()
    except Exception as e:
        logger.critical(f"Failed to initialize RAG components on startup: {e}")
    logger.info("Application startup complete.")

# --- API Routers ---
app.include_router(questions_router.router, prefix="/questions")
app.include_router(answer_router.router, prefix="/answer")
app.include_router(hints_router.router, prefix="/hints")
app.include_router(users_router.router, prefix="/users")
app.include_router(preferences_router.router) # Prefix is defined in the router itself
app.include_router(proactive_hints_router.router) # No prefix needed based on design

# --- Root Endpoint ---
@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API"}


# --- Routers ---
app.include_router(questions.router, prefix="/questions", tags=["Questions"])
app.include_router(answer.router, prefix="/answer", tags=["Answers"])
app.include_router(hints.router, prefix="/hints", tags=["Hints"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(preferences.router) # Added preferences router


@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API (Stage 5.5)."}


# Remove the __main__ block if using lifespan manager correctly with uvicorn
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
