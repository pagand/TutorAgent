# Endpoints to trigger hint generation (proactive/reactive) via the RAG agent
# app/endpoints/hints.py
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class HintRequest(BaseModel):
    question_number: int
    user_answer: str

class HintResponse(BaseModel):
    question_number: int
    hint: str

@router.post("/", response_model=HintResponse)
async def generate_hint(request: HintRequest):
    # For now, we simply return a dummy hint.
    # Later this will call the RAG agent and personalization logic.
    dummy_hint = "Consider reviewing the lecture notes on this topic."
    return HintResponse(question_number=request.question_number, hint=dummy_hint)
