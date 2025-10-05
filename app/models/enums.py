# app/models/enums.py
from enum import Enum

class HintStyle(str, Enum):
    """Enumeration for the different styles of hints that can be generated."""
    ANALOGY = "Analogy"
    SOCRATIC_QUESTION = "Socratic Question"
    WORKED_EXAMPLE = "Worked Example"
    CONCEPTUAL = "Conceptual"

class InterventionPreference(str, Enum):
    """Enumeration for the user's proactive intervention preference."""
    PROACTIVE = "proactive"
    MANUAL = "manual"
