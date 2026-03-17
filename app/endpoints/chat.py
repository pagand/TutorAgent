# app/endpoints/chat.py
# AI tutor chat — context-aware, never reveals the answer directly.
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User, ChatLog
from app.services.question_service import question_service
from app.services.rag_agent import (
    get_user_history_summary,
    _retriever,
    _llm_client,
    format_docs,
    _initialize_rag_components,
)
from app.utils.db import get_db
from app.utils.logger import logger
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

router = APIRouter(prefix="/chat", tags=["Chat"])

CHAT_PROMPT_TEMPLATE = PromptTemplate.from_template(
    """You are a supportive AI tutor helping a student during an exam. Your role is to guide thinking, never to reveal answers directly.

CRITICAL RULES:
- NEVER state the correct answer explicitly, even if directly asked.
- If the student asks for the answer, redirect with a guiding question.
- Keep responses concise: 2-4 sentences maximum.
- Be encouraging and constructive.
- Do not generate useless sentences such as "That is an interesting question" or similar. Try to reframe the original question or the user query followed by your hint.

Current Question:
{question}

Answer Options:
{options}

Student's Current Answer Attempt: {current_answer}

Student's Recent History:
{user_history}

Relevant Educational Context:
{context}

Conversation so far:
{chat_history}

Student's message: {user_message}

Tutor response (guide, don't reveal):"""
)


def _format_chat_history(history: list[dict]) -> str:
    if not history:
        return "No prior messages in this conversation."
    lines = []
    for msg in history:
        role = "Student" if msg.get("role") == "user" else "Tutor"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines)


class ChatMessage(BaseModel):
    role: str   # "user" or "tutor"
    content: str


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    question_number: int
    message: str
    chat_history: list[ChatMessage] = []
    current_answer: str | None = None  # student's current answer attempt if any


class ChatResponse(BaseModel):
    response: str
    question_number: int


@router.post("/", response_model=ChatResponse)
async def chat_with_tutor(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    user_result = await db.execute(select(User).filter_by(id=request.user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    question_obj = question_service.get_question_by_id(request.question_number)
    if not question_obj:
        raise HTTPException(status_code=404, detail="Question not found")

    # Ensure RAG components are ready
    global _retriever, _llm_client
    if not _llm_client or not _retriever:
        if not _initialize_rag_components():
            raise HTTPException(status_code=503, detail="AI components not ready")
        from app.services.rag_agent import _retriever as r, _llm_client as llm
        _retriever = r
        _llm_client = llm

    try:
        # Retrieve relevant context from ChromaDB
        query = f"Question: {question_obj.question}\nStudent message: {request.message}"
        docs = await _retriever.ainvoke(query)
        context = format_docs(docs)

        user_history = await get_user_history_summary(db, request.user_id)
        options_text = "\n".join(f"- {opt}" for opt in question_obj.options) if question_obj.options else "Open-ended question"
        chat_history_text = _format_chat_history([m.model_dump() for m in request.chat_history])

        chain = CHAT_PROMPT_TEMPLATE | _llm_client | StrOutputParser()
        response_text = await chain.ainvoke({
            "question": question_obj.question,
            "options": options_text,
            "current_answer": request.current_answer or "Not provided",
            "user_history": user_history,
            "context": context,
            "chat_history": chat_history_text,
            "user_message": request.message,
        })

        # Log the exchange
        log_entry = ChatLog(
            user_id=request.user_id,
            session_id=request.session_id,
            question_number=request.question_number,
            user_message=request.message,
            tutor_response=response_text,
        )
        db.add(log_entry)
        await db.commit()

        logger.info(f"Chat exchange logged for user {request.user_id} q={request.question_number}")
        return ChatResponse(response=response_text, question_number=request.question_number)

    except Exception as e:
        logger.exception(f"Error in chat endpoint for user {request.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Error generating tutor response")
