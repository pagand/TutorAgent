# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
import asyncio
import hmac
import time
import uuid
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
from app.endpoints.admin_ui import router as admin_ui_router, CSRFOriginMismatch, render_csrf_rejected_page
from app.services import metrics
from app.services.pdf_ingestion import ingest_pdf
from app.services.rag_agent import ensure_rag_components_initialized
from app.services.question_service import question_service
from app.utils.config import settings
from app.utils.logger import logger, request_id_var

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
    
    # Event-loop lag sampler for the admin Health tab. One task, one sleep per
    # second, no I/O - see app/services/metrics.py for why this particular
    # signal is the one worth having on a single-worker box.
    lag_task = asyncio.create_task(metrics.sample_loop_lag())

    logger.warning("Startup complete.")
    yield
    # On shutdown
    lag_task.cancel()
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
    # Reachable only on the loopback-published 8501 port through the SSM
    # tunnel (docker-compose publishes nginx's 8501 on 127.0.0.1, and the
    # listen-80 block CloudFront talks to returns 404 for /admin). AWS IAM
    # plus SSM is the auth boundary here, the same trust model the
    # Streamlit dashboard had.
    if request.url.path.startswith("/admin"):
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


# --- Request logging and metrics ---
# Registered LAST, so it ends up outermost and sees every response including the
# api-key middleware's 401s. This does not disturb the ordering invariant
# documented above (CORS must stay outermost of the api-key middleware) - adding
# a layer outside CORS leaves that relationship intact.
def _route_template(request: Request) -> str:
    """The matched route's path template, never the concrete URL.

    "/admin/user/{user_id}" rather than "/admin/user/3XMFN8TA", so the metrics
    dict is bounded by the number of routes instead of growing with every user
    id. Anything that matched no route at all collapses into one bucket, so a
    scanner spraying random paths cannot grow it either - metrics.py's other
    structures are all maxlen-bounded, and this dict is the one that would
    otherwise not be.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if not path:
        return f"{request.method} <unmatched>"
    return f"{request.method} {path}"


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    metrics.in_flight += 1
    status = 500
    exc_detail = None
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        exc_detail = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        metrics.in_flight -= 1
        duration_ms = (time.perf_counter() - started) * 1000.0
        # Resolved here rather than before call_next: scope["route"] is only
        # populated once routing has run, and scope is mutated in place.
        route = _route_template(request)
        metrics.record_request(route, status, duration_ms)
        if exc_detail is not None:
            metrics.record_error(route, 500, request_id, exc_detail)
        elif status >= 500:
            metrics.record_error(route, status, request_id, f"HTTP {status}")
        logger.info(
            "request",
            extra={"fields": {
                "method": request.method,
                "path": request.url.path,
                "route": route,
                "status": status,
                "duration_ms": round(duration_ms, 1),
            }},
        )
        request_id_var.reset(token)

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
app.include_router(admin_ui_router)


@app.exception_handler(CSRFOriginMismatch)
async def _handle_csrf_origin_mismatch(request: Request, exc: CSRFOriginMismatch):
    return render_csrf_rejected_page()


# --- Root Endpoint ---
@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API"}
