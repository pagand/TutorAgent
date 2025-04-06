# Configures Python’s built-in logging module to monitor the various stages and component calls
# app/utils/logger.py
import logging

def setup_logger():
    logger = logging.getLogger("ai_tutor")
    logger.setLevel(logging.DEBUG)

    # Create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    
    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    
    # Add the handlers to the logger
    if not logger.hasHandlers():
        logger.addHandler(ch)
    
    return logger

logger = setup_logger()
