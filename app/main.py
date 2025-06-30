# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
# Import routers
from app.endpoints import questions, hints, feedback, answer, users, preferences
# Import services/utils needed at startup
from app.services.pdf_ingestion import ingest_pdf
from app.services.rag_agent import ensure_rag_components_initialized # Import the check function
from app.services.question_service import question_service
from app.utils.config import settings
from app.utils.logger import logger
import sys # Import sys for exit

# --- Global State (Simple approach for POC) ---
# No explicit global needed here now as state_manager handles it internally
# and services are imported directly where needed.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("AI Tutor API starting up...")

    # 1. Load Questions (must happen before RAG/BKT initialization if they depend on skills)
    logger.info("Loading questions...")
    try:
         # --- CALL LOAD_QUESTIONS EXPLICITLY ---
        # It will use settings.QUESTION_CSV_FILE_PATH by default
        question_service.load_questions()
        if not question_service.get_all_questions():
             logger.error("Question service loaded no questions. Check CSV path and content.")
             # Decide if this is critical - likely yes for BKT/Answering
             sys.exit("Exiting: No questions loaded.")
    except Exception as e:
        logger.exception("CRITICAL FAILURE during question loading.")
        sys.exit("Exiting due to failure loading questions.")

    # 2. PDF Ingestion (run once if needed)
    logger.info("Checking for PDF ingestion...")
    try:
        ingest_pdf() # Run the ingestion function
    except Exception as e:
        logger.exception("Error during PDF ingestion check/run. This might affect RAG.")
        # Decide if this is critical enough to stop startup
        # sys.exit("Failed during PDF ingestion phase.")

    # 3. Initialize Core RAG Components (Embeddings, DB connection, LLM check)
    logger.info("Initializing RAG components...")
    try:
        ensure_rag_components_initialized() # Trigger initialization
    except Exception as e:
        logger.exception("CRITICAL FAILURE during RAG component initialization.")
        # Exit if core components fail, as the app is likely unusable
        sys.exit("Exiting due to failure initializing core RAG components.")

    logger.info("Startup complete. RAG Components initialized.")
    yield
    # Shutdown logic (if any needed)
    logger.info("AI Tutor API shutting down...")

# --- Rest of main.py remains the same ---
# Initialize FastAPI app with the lifespan manager
app = FastAPI(title="AI Tutor POC - Stage 4", lifespan=lifespan)

app.include_router(questions.router, prefix="/questions", tags=["Questions"])
app.include_router(hints.router, prefix="/hints", tags=["Hints"])
app.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
app.include_router(answer.router, prefix="/answer", tags=["Answer Submission"]) # Added answer router
app.include_router(users.router)
app.include_router(preferences.router, prefix="/users", tags=["Preferences"])

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API (Stage 4)."}


# Remove the __main__ block if using lifespan manager correctly with uvicorn
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
