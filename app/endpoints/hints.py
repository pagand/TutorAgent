# Endpoints to trigger hint generation (proactive/reactive) via the RAG agent
# app/endpoints/hints.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services import rag_agent # Import the new service
from app.utils.logger import logger

router = APIRouter()

class HintRequest(BaseModel):
    user_id: str # Added user_id
    question_number: int
    user_answer: str | None = None # Made user_answer optional


class HintResponse(BaseModel):
    question_number: int
    hint: str
    user_id: str # Added user_id back for clarity

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest):
    logger.info(f"Hint requested by user '{request.user_id}' for question {request.question_number}")

    # --- TODO: Fetch actual question text using request.question_number ---
    # This requires accessing the loaded QUESTIONS list from questions.py
    # Or preferably, creating a shared way to access questions (e.g., a service)
    # For now, let's assume we have the question text (replace with actual lookup)
    from app.endpoints.questions import QUESTIONS # Quick and dirty access for now
    question_obj = next((q for q in QUESTIONS if q.question_number == request.question_number), None)

    if not question_obj:
         logger.warning(f"Question number {request.question_number} not found for hint request.")
         raise HTTPException(status_code=404, detail="Question not found")

    question_text = question_obj.question
    # --- End TODO ---


    try:
        # Call the RAG agent service function
        generated_hint = await rag_agent.get_rag_hint(question_text, request.user_answer)

        if not generated_hint:
             # Handle cases where RAG agent returns empty or error messages internally
             logger.warning(f"RAG agent returned no hint for question {request.question_number}")
             # Return a generic hint or the RAG agent's error message
             generated_hint = "I couldn't generate a specific hint right now. Try reviewing the main concepts."


        return HintResponse(
            question_number=request.question_number,
            hint=generated_hint,
            user_id=request.user_id
        )
    except Exception as e:
        logger.exception(f"Unhandled error in hint endpoint for question {request.question_number}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error generating hint")
