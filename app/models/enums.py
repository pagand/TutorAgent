# app/models/enums.py
from enum import Enum

class HintStyle(str, Enum):
    """Enumeration for the different styles of hints."""
    ANALOGY = "Analogy"
    SOCRATIC_QUESTION = "Socratic Question"
    WORKED_EXAMPLE = "Worked Example"
    CONCEPTUAL = "Conceptual"
    AUTOMATIC = "Automatic" # Represents user's choice to let the system decide