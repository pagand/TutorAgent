# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
import hmac
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    proactive_hints as proactive_hints_router,
)
from app.endpoints.session import router as session_router
from app.endpoints.chat import router as chat_router
from app.endpoints.action_log import router as action_log_router
from app.endpoints.participants import router as participants_router
from app.services.pdf_ingestion import ingest_pdf
from app.services.rag_agent import ensure_rag_components_initialized
from app.services.question_service import question_service
from app.utils.config import settings
from app.utils.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application startup and shutdown events.
    """
    logger.info("AI Tutor API starting up...")

    # Fail loud rather than silently serving a weaker posture. Only checked
    # when APP_ENV=production (set by scripts/ec2-bootstrap.sh) so a plain
    # `.venv` dev run, which never sets APP_ENV, is unaffected.
    if settings.app_env == "production":
        missing = []
        if not settings.api_key:
            missing.append("API_KEY")
        if _allowed_origin == "*":
            missing.append("ALLOWED_ORIGIN")
        if not settings.require_participant_token:
            missing.append("REQUIRE_PARTICIPANT_TOKEN")
        if missing:
            raise RuntimeError(
                f"APP_ENV=production but the following are not set correctly: {', '.join(missing)}. "
                "Refusing to boot with a weaker-than-production security posture."
            )

    logger.info("Loading questions...")
    question_service.load_questions(settings.QUESTION_CSV_FILE_PATH)
    if not question_service.get_all_questions():
        raise RuntimeError(
            f"No questions loaded from '{settings.QUESTION_CSV_FILE_PATH}'. "
            "Check the file exists and is readable inside the container."
        )
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
    
    logger.warning("Startup complete.")
    yield
    # On shutdown
    logger.info("AI Tutor API shutting down...")

# --- FastAPI App Initialization ---
# /docs, /redoc and /openapi.json are still gated by the X-API-Key middleware
# below like any other route once API_KEY is set, but that key is only
# obscurity (it ships in the public frontend bundle) - disabling the schema
# outright in that configuration is one less thing a scanner holding the key
# can trivially enumerate (every route, every field, DELETE included).
_docs_enabled = not settings.api_key
app = FastAPI(
    title="AI Tutor API",
    description="API for a personalized AI-powered tutor.",
    version="0.7.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# --- API Key Middleware ---
# Registered before CORSMiddleware below: Starlette applies the last-added
# middleware outermost, so CORS must end up outermost to attach CORS headers
# even to the 401s this middleware returns — otherwise a rejected request
# looks like a CORS failure in the browser instead of the real 401.
# settings.api_key is read per-request (not captured here) so tests can
# monkeypatch it without reloading the module.
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if not settings.api_key:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path == "/":
        return await call_next(request)
    provided = request.headers.get("X-API-Key", "")
    # Compare as bytes — hmac.compare_digest raises TypeError on a str containing
    # non-ASCII characters, which would otherwise turn a scanner probing with a
    # UTF-8 header into an unhandled 500 instead of a clean 401.
    if not hmac.compare_digest(provided.encode("utf-8", "replace"), settings.api_key.get_secret_value().encode("utf-8")):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

# --- CORS Middleware ---
# Set ALLOWED_ORIGIN to your CloudFront domain in production.
# If unset or "*", open CORS is used (dev-only) and credentials are disabled
# because browsers reject allow_credentials=True with a wildcard origin.
_allowed_origin = os.getenv("ALLOWED_ORIGIN", "*")
if _allowed_origin == "*":
    logger.warning("CORS: ALLOWED_ORIGIN='*' — open CORS without credentials (development only)")
    _cors_origins = ["*"]
    _cors_credentials = False
else:
    _cors_origins = [_allowed_origin]
    _cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
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
app.include_router(session_router)
app.include_router(chat_router)
app.include_router(action_log_router)
app.include_router(participants_router)

# --- Root Endpoint ---
@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API"}
