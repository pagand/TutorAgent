# app/utils/logger.py
import logging
import sys
from app.utils.config import settings # <-- ADDED

# Get the logger instance for our application.
logger = logging.getLogger("ai_tutor")

# Set the level from the settings file, defaulting to INFO if the level is invalid.
log_level = getattr(logging, settings.log_level, logging.INFO)
logger.setLevel(log_level)

# Clear any existing handlers to prevent duplicate logs during hot-reloads.
if logger.hasHandlers():
    logger.handlers.clear()

# Create a handler that writes to standard output.
handler = logging.StreamHandler(sys.stdout)

# Create a formatter with our desired, more detailed format.
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add our custom handler to the logger.
logger.addHandler(handler)

# Prevent log messages from being passed to the root logger to avoid double printing.
logger.propagate = False
