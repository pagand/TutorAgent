# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.endpoints import questions, hints, feedback
from app.services.pdf_ingestion import ingest_pdf
from app.services.rag_agent import ensure_rag_components_initialized # Import the check function
from app.utils.logger import logger
from app.utils.config import settings
import os
import sys # Import sys for exit

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("AI Tutor API starting up...")

    # 1. PDF Ingestion (run once if needed)
    logger.info("Checking for PDF ingestion...")
    try:
        ingest_pdf() # Run the ingestion function
    except Exception as e:
        logger.exception("Error during PDF ingestion check/run. This might affect RAG.")
        # Decide if this is critical enough to stop startup
        # sys.exit("Failed during PDF ingestion phase.")

    # 2. Initialize Core RAG Components (Embeddings, DB connection, LLM check)
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
app = FastAPI(title="AI Tutor POC - Stage 2", lifespan=lifespan)

app.include_router(questions.router, prefix="/questions", tags=["Questions"])
app.include_router(hints.router, prefix="/hints", tags=["Hints"])
app.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API (Stage 2)."}


# Remove the __main__ block if using lifespan manager correctly with uvicorn
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
