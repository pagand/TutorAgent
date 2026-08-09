# app/utils/logger.py
import json
import logging
import sys
from contextvars import ContextVar

from app.utils.config import settings

# Set by app/main.py's request-logging middleware for the duration of a request,
# so every log line emitted anywhere inside that request carries the same id.
#
# This is how an app log line that names a user (app/services/llm_quota.py's
# per-user cap warning, for instance) gets joined back to the request that
# produced it. The middleware deliberately does NOT read the request body to
# extract user_id itself - consuming the body stream in middleware breaks
# downstream handlers - so the request id is the join key rather than the user id.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so the log stream is queryable by field.

    PRELAUNCH_CHECKLIST.md section E: plain text meant "it broke at 10:42"
    could only be answered by grepping stdout by timestamp and guessing.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg": record.getMessage(),
        }
        # Structured fields ride in `extra={"fields": {...}}` rather than being
        # formatted into the message string, which is the whole point of doing
        # this: the middleware's duration_ms stays a number, not text.
        fields = getattr(record, "fields", None)
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


logger = logging.getLogger("ai_tutor")

# Set the level from the settings file, defaulting to INFO if the level is invalid.
log_level = getattr(logging, settings.log_level, logging.INFO)
logger.setLevel(log_level)

# Clear any existing handlers to prevent duplicate logs during hot-reloads.
if logger.hasHandlers():
    logger.handlers.clear()

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)

# Prevent log messages from being passed to the root logger to avoid double printing.
logger.propagate = False

# Apply the same level AND the same formatter to uvicorn's loggers, so the whole
# stdout stream is one machine-parseable format rather than JSON interleaved with
# uvicorn's plain text. uvicorn configures these when the server boots, which is
# before it imports the app, so replacing them here sticks.
#
# "uvicorn.access" is deliberately NOT in this list, and adding it back would be
# a real regression rather than a tidy-up. uvicorn implements --no-access-log
# (entrypoint.sh) by clearing that logger's handlers, not by suppressing the
# records - so attaching a handler here re-enables the access log the flag exists
# to switch off. That was observed live on the deployed box: every request logged
# twice, once by the middleware and once by uvicorn.access, which is exactly the
# duplication the flag was added to prevent, on a container log capped at
# 10MB x 3 by docker-compose.yml's x-logging anchor.
for _uv_name in ("uvicorn", "uvicorn.error"):
    _uv_logger = logging.getLogger(_uv_name)
    _uv_logger.setLevel(log_level)
    _uv_logger.handlers.clear()
    _uv_logger.addHandler(handler)
    _uv_logger.propagate = False
