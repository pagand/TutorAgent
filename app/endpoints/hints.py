# Endpoints to trigger hint generation (proactive/reactive) via the RAG agent
# app/endpoints/hints.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services import rag_agent # Import the RAG service
# Import the shared question service instance
from app.services.question_service import question_service
from app.utils.logger import logger

router = APIRouter()

class HintRequest(BaseModel):
    user_id: str
    question_number: int
    user_answer: str | None = None


class HintResponse(BaseModel):
    question_number: int
    hint: str
    user_id: str

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest):
    logger.info(f"Hint requested by user '{request.user_id}' for question {request.question_number}")

    # --- Fetch question text using the QuestionService ---
    question_obj = question_service.get_question_by_id(request.question_number) # Use the service

    if not question_obj:
         logger.warning(f"Question number {request.question_number} not found for hint request.")
         # Raise 404 if the question doesn't exist
         raise HTTPException(status_code=404, detail="Question not found")

    question_text = question_obj.question
    # --- Question text successfully retrieved ---

    try:
        # Call the RAG agent service function
        # Pass the actual question text and the user's answer (if any)
        generated_hint = await rag_agent.get_rag_hint(question_text, request.user_answer)

        if not generated_hint or "Sorry," in generated_hint or "unable to retrieve" in generated_hint:
             # Handle cases where RAG agent returns empty or known error messages
             logger.warning(f"RAG agent provided no specific hint for question {request.question_number}")
             # Return a more generic hint if RAG failed
             generated_hint = "I couldn't generate a specific hint right now. Can you try thinking about the main concept of the question?"

        return HintResponse(
            question_number=request.question_number,
            hint=generated_hint,
            user_id=request.user_id
        )
    except Exception as e:
        logger.exception(f"Unhandled error in hint endpoint for question {request.question_number}: {e}")
        # Return a 500 Internal Server Error for unexpected issues
        raise HTTPException(status_code=500, detail="Internal server error generating hint")