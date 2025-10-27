# Retrieval-Augmented Generation component; integrates local LLM (via Hugging Face Transformers and Langchain) to generate personalized hints
# app/services/rag_agent.py
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings # LLM Imports
from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain_aws import BedrockChat # Add if using Bedrock
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langchain_core.vectorstores import VectorStoreRetriever

from app.utils.config import settings
from app.utils.logger import logger
import threading
import os

from operator import itemgetter # Import itemgetter
from app.services.personalization_service import personalization_service
from app.services.prompt_library import PROMPT_LIBRARY
from app.services.question_service import question_service # Import question_service

# --- Global variables for initialized components (initialized lazily) ---
_embedding_function = None
_vectorstore = None
_retriever = None
_llm_client = None
# --- RAG chain is no longer a single global variable, it's built dynamically ---
_init_lock = threading.Lock()

from app.models.user import InteractionLog
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Helper Functions ---
def format_docs(docs):
    """Joins document page content into a single string."""
    if not docs:
        return "No relevant context found."
    return "\n\n".join(doc.page_content for doc in docs)

async def get_user_history_summary(session: AsyncSession, user_id: str, limit: int = 5) -> str:
    """
    Retrieves and formats the last N interactions for a user into a structured,
    XML-tagged summary for the LLM. Translates MC answer indexes to full text.
    """
    result = await session.execute(
        select(InteractionLog)
        .filter_by(user_id=user_id)
        .order_by(InteractionLog.timestamp.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    if not logs:
        return "No recent interactions found."

    summary = []
    for log in reversed(logs):  # Oldest to newest
        question = question_service.get_question_by_id(log.question_id)
        if not question:
            continue

        question_text = question.question.replace('\n', ' ')
        status = "Correct" if log.is_correct else "Incorrect"
        answer_text = log.user_answer

        # --- NEW: Translate multiple-choice answer index to text ---
        if question.question_type == 'multiple_choice':
            try:
                # Convert 1-based answer string to 0-based index
                answer_index = int(log.user_answer) - 1
                if 0 <= answer_index < len(question.options):
                    answer_text = question.options[answer_index]
                else:
                    logger.warning(f"Invalid answer index '{log.user_answer}' for question {log.question_id}")
            except (ValueError, TypeError):
                # Handle cases where answer is not a valid number
                logger.warning(f"Could not parse answer index '{log.user_answer}' for question {log.question_id}")
        # --- END NEW ---

        # --- RESTRUCTURED SUMMARY ---
        summary_parts = [f"<q>{question_text}</q>"]
        if log.hint_shown and log.hint_style_used and log.hint_text:
            hint_content = log.hint_text.replace('\n', ' ').strip()
            summary_parts.append(f"<h>Hint Style Used: {log.hint_style_used}: {hint_content}</h>")
        summary_parts.append(f"<a>{answer_text}</a> ({status})")
        
        summary_line = "- " + "; ".join(summary_parts)
        summary.append(summary_line)
        # --- END RESTRUCTURED SUMMARY ---
        
    return "\n".join(summary)


def create_retrieval_query(input_dict: dict) -> str:
    """Combines question and user answer for richer retrieval context."""
    question = input_dict["question"]
    user_answer = input_dict.get("user_answer") or "Not provided" # Handle None case
    # Combine them for embedding search query
    combined_query = f"Question: {question}\nStudent Answer: {user_answer}"
    logger.debug(f"Created retrieval query: {combined_query[:100]}...")
    return combined_query

# --- Initialization Function ---
def _initialize_rag_components():
    """Initializes all RAG components if not already done. Returns True on success, False on failure."""
    global _embedding_function, _vectorstore, _retriever, _llm_client

    with _init_lock:
        if _llm_client and _retriever: # Check if core components are already initialized
            return True

        logger.info("Attempting to initialize RAG components...")
        try:
            # 1. Initialize Embeddings
            if _embedding_function is None:
                logger.info(f"Loading embedding model: {settings.embedding_model_name}")
                _embedding_function = HuggingFaceEmbeddings(
                    model_name=settings.embedding_model_name,
                    cache_folder=settings.hf_cache_dir or None,
                )
                logger.info("Embedding model loaded.")

            # 2. Initialize Vector Store and Retriever
            if _vectorstore is None:
                logger.info(f"Connecting to ChromaDB at {settings.chroma_persist_dir}, collection: {settings.chroma_collection_name}")
                _vectorstore = Chroma(
                    persist_directory=settings.chroma_persist_dir,
                    collection_name=settings.chroma_collection_name,
                    embedding_function=_embedding_function,
                )
                _retriever = _vectorstore.as_retriever(search_kwargs={"k": settings.retrieval_k})
                count = _vectorstore._collection.count()
                logger.info(f"ChromaDB retriever initialized successfully. Collection count: {count}")
                if count == 0:
                     logger.warning("ChromaDB collection is empty. Ensure PDF ingestion ran successfully.")

            # 3. Initialize LLM
            if _llm_client is None:
                logger.info(f"Initializing LLM client for provider: {settings.llm_provider}")
                provider = settings.llm_provider
                if provider == "ollama":
                    _llm_client = Ollama(base_url=settings.ollama_base_url, model=settings.ollama_model)
                elif provider == "openai":
                    _llm_client = ChatOpenAI(openai_api_key=settings.openai_api_key, model_name=settings.openai_model_name, temperature=0)
                elif provider == "google":
                    _llm_client = ChatGoogleGenerativeAI(google_api_key=settings.google_api_key, model=settings.google_model_name, temperature=0, convert_system_message_to_human=True, max_output_tokens = settings.max_output_tokens)
                else:
                    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
                logger.info(f"Initialized LLM with provider {provider}")

            return True

        except Exception as e:
            logger.exception(f"CRITICAL: Failed to initialize RAG components: {e}")
            # Reset all components on failure
            _embedding_function = _vectorstore = _retriever = _llm_client = None
            return False

def get_rag_chain(hint_style: str):
    """Builds and returns a RAG chain for a specific hint style."""
    if not _llm_client or not _retriever:
        raise RuntimeError("RAG components not initialized.")

    base_prompt = PROMPT_LIBRARY.get(hint_style)
    if not base_prompt:
        logger.warning(f"Hint style '{hint_style}' not found in PROMPT_LIBRARY. Falling back to 'Conceptual'.")
        base_prompt = PROMPT_LIBRARY["Conceptual"]

    rag_prompt = PromptTemplate.from_template(base_prompt.template)

    # --- DEFINITIVE FIX: Re-architect the chain for clarity and correctness ---
    setup_and_retrieval = RunnableParallel({
        "context": RunnableLambda(create_retrieval_query) | _retriever | format_docs,
        "question": itemgetter("question"),
        "options": itemgetter("options"),
        "user_answer": itemgetter("user_answer"),
        "user_history": itemgetter("user_history"),
    })

    generation_chain = RunnableParallel({
        "final_prompt": rag_prompt,
        "context": itemgetter("context"),
        "generated_hint": rag_prompt | _llm_client | StrOutputParser()
    })
    
    rag_chain = setup_and_retrieval | generation_chain
    # --- END FIX ---
    
    return rag_chain

# --- Hint Generation Function ---
async def get_rag_hint(session: AsyncSession, question_id: int, user_answer: str | None, user_id: str, user_history: str) -> dict:
    """
    Retrieves context, gets adaptive hint style, and generates a personalized hint.
    Returns a dictionary containing the hint, style, context, and final prompt.
    """
    if not _llm_client:
        if not _initialize_rag_components():
            logger.error("RAG components failed to initialize. Cannot generate hint.")
            return {"hint": "...", "hint_style": "error", "context": "", "final_prompt": ""}

    try:
        question_obj = question_service.get_question_by_id(question_id)
        if not question_obj:
            return {"hint": "...", "hint_style": "error", "context": "", "final_prompt": ""}

        hint_style = await personalization_service.get_adaptive_hint_style(session, user_id)
        
        if "test_user" in user_id:
            return {"hint": "...", "hint_style": hint_style, "context": "Mock context", "final_prompt": "Mock prompt"}

        logger.info(f"Generating RAG hint for user {user_id} with style: '{hint_style}'...")
        rag_chain = get_rag_chain(hint_style)

        options_text = "\n".join(f"- {opt}" for opt in question_obj.options) if question_obj.options else ""

        input_data = {
            "question": question_obj.question,
            "options": options_text,
            "user_answer": user_answer or "Not provided",
            "user_history": user_history,
        }
        
        result = await rag_chain.ainvoke(input_data)
        
        final_prompt_str = result['final_prompt'].to_string()
        logger.debug(f"--- FINAL PROMPT FOR LLM ---\n{final_prompt_str}\n---------------------------")

        return {
            "hint": result['generated_hint'], 
            "hint_style": hint_style,
            "context": result['context'],
            "final_prompt": final_prompt_str
        }

    except Exception as e:
        logger.exception(f"Error generating RAG hint for user {user_id}: {e}")
        return {"hint": "...", "hint_style": "error", "context": "", "final_prompt": ""}

# --- Optional: Function to explicitly trigger initialization during startup ---
def ensure_rag_components_initialized():
    """Public function to trigger initialization, e.g., during app startup."""
    if not _llm_client:
        if not _initialize_rag_components():
             raise RuntimeError("Failed to initialize critical RAG components during startup check.")
        else:
             logger.info("RAG components initialized successfully during startup check.")
    else:
        logger.info("RAG components already initialized.")