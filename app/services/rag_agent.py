# Retrieval-Augmented Generation component; integrates local LLM (via Hugging Face Transformers and Langchain) to generate personalized hints
# app/services/rag_agent.py
from langchain_community.vectorstores import Chroma
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

# --- Global variables for initialized components (initialized lazily) ---
_embedding_function = None
_vectorstore = None
_retriever = None
_llm_client = None
# --- RAG chain is no longer a single global variable, it's built dynamically ---
_init_lock = threading.Lock()

# --- Helper Functions ---
def format_docs(docs):
    """Joins document page content into a single string."""
    if not docs:
        return "No relevant context found."
    return "\n\n".join(doc.page_content for doc in docs)

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
                    _llm_client = ChatGoogleGenerativeAI(google_api_key=settings.google_api_key, model=settings.google_model_name, temperature=0, convert_system_message_to_human=True)
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

    rag_prompt = PROMPT_LIBRARY.get(hint_style)
    if not rag_prompt:
        logger.warning(f"Hint style '{hint_style}' not found in PROMPT_LIBRARY. Falling back to 'Conceptual'.")
        rag_prompt = PROMPT_LIBRARY["Conceptual"]

    # The chain is now built on-demand based on the hint style
    rag_chain = (
        RunnablePassthrough.assign(context=(RunnableLambda(create_retrieval_query) | _retriever | format_docs))
        | rag_prompt
        | _llm_client
        | StrOutputParser()
    )
    return rag_chain

# --- Hint Generation Function ---
async def get_rag_hint(question_text: str, user_answer: str | None, user_id: str) -> dict:
    """
    Retrieves context, gets adaptive hint style, and generates a personalized hint.
    Returns a dictionary containing the hint and the style used.
    """
    if not _llm_client:
        if not _initialize_rag_components():
            logger.error("RAG components failed to initialize. Cannot generate hint.")
            return {
                "hint": "Sorry, the AI Tutor components could not be initialized. Please contact support.",
                "hint_style": "error"
            }

    try:
        # This service will eventually contain the adaptive logic
        hint_style = personalization_service.get_adaptive_hint_style(user_id)
        logger.info(f"Generating RAG hint for user {user_id} with style: '{hint_style}' (Provider: {settings.llm_provider})")

        # Dynamically get the chain for the chosen style
        rag_chain = get_rag_chain(hint_style)

        input_data = {
            "question": question_text,
            "user_answer": user_answer or "Not provided",
        }

        # Invoke the RAG chain
        generated_hint = await rag_chain.ainvoke(input_data)
        logger.info(f"Generated hint: {generated_hint[:100]}...")

        return {"hint": generated_hint, "hint_style": hint_style}

    except Exception as e:
        logger.exception(f"Error generating RAG hint for user {user_id}: {e}")
        return {
            "hint": "There was an error while trying to generate a hint for you. Please try again.",
            "hint_style": "error"
        }

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