# app/endpoints/chat.py
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User, ChatLog
from app.services.question_service import question_service
import app.services.rag_agent as rag_agent
from app.services.rag_agent import get_user_history_summary, format_docs
from app.utils.authz import verify_session_owner
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


CHAT_HISTORY_TURNS = 6  # how many recent exchanges to feed back into the prompt


def _format_chat_history(history: list[dict]) -> str:
    if not history:
        return "No prior messages in this conversation."
    lines = []
    for msg in history:
        role = "Student" if msg.get("role") == "user" else "Tutor"
        lines.append(f"{role}: {msg.get('content', '')}")
    return "\n".join(lines)


async def _recent_chat_history_text(db: AsyncSession, user_id: str, limit: int = CHAT_HISTORY_TURNS) -> str:
    """Reads the conversation from ChatLog rather than trusting the client's
    own chat_history - a client-fabricated transcript (e.g. a fake tutor turn
    that already "reveals" the answer) would otherwise be rendered into the
    prompt as authoritative prior context, defeating the CRITICAL RULES above
    it. Global across questions, matching the frontend's persistent ChatPanel."""
    result = await db.execute(
        select(ChatLog).filter_by(user_id=user_id).order_by(ChatLog.timestamp.desc()).limit(limit)
    )
    logs = list(reversed(result.scalars().all()))
    history: list[dict] = []
    for log in logs:
        history.append({"role": "user", "content": log.user_message})
        history.append({"role": "tutor", "content": log.tutor_response})
    return _format_chat_history(history)


class ChatMessage(BaseModel):
    role: str   # "user" or "tutor"
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    question_number: int
    message: str = Field(max_length=2000)
    # Accepted for wire compatibility with the documented contract, but no
    # longer used to build the prompt - see _recent_chat_history_text.
    chat_history: list[ChatMessage] = Field(default=[], max_length=100)
    current_answer: str | None = Field(None, max_length=2000)


class ChatResponse(BaseModel):
    response: str
    question_number: int


@router.post("/", response_model=ChatResponse)
async def chat_with_tutor(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    await verify_session_owner(db, request.user_id, request.session_id)
    user_result = await db.execute(select(User).filter_by(id=request.user_id))
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    question_obj = question_service.get_question_by_id(request.question_number)
    if not question_obj:
        raise HTTPException(status_code=404, detail="Question not found")

    if not rag_agent._llm_client or not rag_agent._retriever:
        if not rag_agent._initialize_rag_components():
            raise HTTPException(status_code=503, detail="AI components not ready")

    user_history = await get_user_history_summary(db, request.user_id)
    chat_history_text = await _recent_chat_history_text(db, request.user_id)

    # Release the DB connection before the slow LLM/retriever calls
    await db.commit()

    try:
        query = f"Question: {question_obj.question}\nStudent message: {request.message}"
        docs = await rag_agent._retriever.ainvoke(query)
        context = format_docs(docs)

        options_text = "\n".join(f"- {opt}" for opt in question_obj.options) if question_obj.options else "Open-ended question"

        chain = CHAT_PROMPT_TEMPLATE | rag_agent._llm_client | StrOutputParser()
        response_text = await chain.ainvoke({
            "question": question_obj.question,
            "options": options_text,
            "current_answer": request.current_answer or "Not provided",
            "user_history": user_history,
            "context": context,
            "chat_history": chat_history_text,
            "user_message": request.message,
        })

        # Re-acquire a connection only for the write
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
