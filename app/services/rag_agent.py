# Retrieval-Augmented Generation component; integrates local LLM (via Hugging Face Transformers and Langchain) to generate personalized hints
# app/services/rag_agent.py
from langchain_community.vectorstores import Chroma
# Corrected import based on previous discussion and deprecation warnings
from langchain_huggingface import HuggingFaceEmbeddings
# Corrected import based on previous discussion and deprecation warnings
from langchain_community.llms import Ollama
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel, RunnableLambda
from langchain_core.output_parsers import StrOutputParser
from langchain_core.vectorstores import VectorStoreRetriever
from operator import itemgetter # Import itemgetter

from app.utils.config import settings
from app.utils.logger import logger
import threading

# --- Global variables ---
_embedding_function = None
_vectorstore = None
_retriever = None
_ollama_llm = None
_rag_chain_with_source = None
_init_lock = threading.Lock()

# --- Updated Prompt Template ---
# Explicitly structure the information for the LLM
template = """
**Instructions:** You are an AI Tutor. Your goal is to provide a helpful hint to a student based on their question and their answer attempt, using the provided context. Focus on clarifying the core concept without giving away the direct answer. If the context isn't relevant, acknowledge that and offer general advice related to the question's topic. Keep the hint concise, encouraging, and focused.

**Retrieved Context:**
---------------------
{context}
---------------------

**Student's Question:** {question}

**Student's Answer Attempt:** {user_answer}

**Hint:**
"""
rag_prompt = PromptTemplate.from_template(template)

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
    global _embedding_function, _vectorstore, _retriever, _ollama_llm, _rag_chain_with_source

    with _init_lock:
        if _rag_chain_with_source is not None:
            return True

        logger.info("Attempting to initialize RAG components...")
        try:
            # 1. Initialize Embeddings (Using langchain_huggingface)
            if _embedding_function is None:
                logger.info(f"Loading embedding model: {settings.embedding_model_name}")
                # Use the correct class from the dedicated package
                _embedding_function = HuggingFaceEmbeddings(
                    model_name=settings.embedding_model_name,
                    cache_folder=settings.hf_cache_dir or None, # Use cache setting
                    # Consider adding model_kwargs={'device': 'cpu'} if GPU issues arise
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

            # 3. Initialize LLM (Using langchain_ollama)
            if _ollama_llm is None:
                logger.info(f"Initializing Ollama LLM client for model '{settings.ollama_model}' at {settings.ollama_base_url}")
                 # Use the correct class from the dedicated package
                _ollama_llm = Ollama(
                    base_url=settings.ollama_base_url,
                    model=settings.ollama_model
                )
                logger.info("Ollama LLM client initialized.")

            # 4. Define RAG Chain (Revised Logic)
            if _retriever and _ollama_llm and rag_prompt:
                logger.info("Defining revised RAG chain...")

                # Chain Part 1: Prepare input and retrieve documents
                # Takes original dict {"question": ..., "user_answer": ...}
                # Outputs dict {"question": ..., "user_answer": ..., "context": [Docs]}
                retrieval_augmented_chain = RunnablePassthrough.assign(
                    # Create the combined query string and retrieve documents based on it
                    context = RunnableLambda(create_retrieval_query) | _retriever
                )
                # Output at this point includes original question/answer + retrieved context docs

                # Chain Part 2: Format docs, generate hint, and structure output
                # Takes the output from Part 1
                # Outputs the final dict {"question": ..., "user_answer": ..., "context": [Docs], "answer": "..."}
                rag_chain_final = RunnableParallel(
                     {
                         # Generate the hint using formatted context, question, and user_answer
                         "answer": (
                              RunnablePassthrough.assign(
                                  # Format the retrieved docs *specifically* for the prompt input
                                  context=lambda x: format_docs(x["context"])
                              )
                              | rag_prompt   # Use the updated prompt template
                              | _ollama_llm  # Call the LLM
                              | StrOutputParser() # Parse the LLM output string
                         ),
                         # Pass through the original retrieved documents (context)
                         "context": itemgetter("context"),
                         # Pass through the original question
                         "question": itemgetter("question"),
                         # Pass through the original user_answer
                         "user_answer": itemgetter("user_answer"),
                     }
                 )


                # Combine the parts: First retrieve, then format/generate in parallel
                _rag_chain_with_source = retrieval_augmented_chain | rag_chain_final

                logger.info("Revised RAG chain defined successfully.")
                return True
            else:
                 logger.error("Failed to define revised RAG chain due to missing components.")
                 return False

        except Exception as e:
            logger.exception(f"CRITICAL: Failed to initialize RAG components: {e}")
            _embedding_function = None
            _vectorstore = None
            _retriever = None
            _ollama_llm = None
            _rag_chain_with_source = None
            return False


# --- Hint Generation Function (No changes needed here) ---
async def get_rag_hint(question_text: str, user_answer: str | None) -> str:
    """
    Retrieves context from ChromaDB and generates a hint using Ollama.
    Ensures components are initialized before use.
    """
    global _rag_chain_with_source

    if _rag_chain_with_source is None:
        if not _initialize_rag_components():
            logger.error("RAG components failed to initialize. Cannot generate hint.")
            return "Sorry, the AI Tutor components could not be initialized. Please contact support or try again later."

    if _rag_chain_with_source is None:
         logger.error("RAG chain is still None even after initialization attempt.")
         return "An unexpected error occurred while preparing the hint generator."

    try:
        logger.info(f"Generating RAG hint for question: {question_text}")
        input_data = {"question": question_text, "user_answer": user_answer} # Ensure user_answer can be None

        # Invoke the revised chain
        # The chain now outputs a dict like:
        # {"question": ..., "user_answer": ..., "context": [Docs...], "answer": "..."}
        result = await _rag_chain_with_source.ainvoke(input_data)

        generated_hint = result.get("answer", "Sorry, I couldn't generate a hint based on the available information.")
        retrieved_docs = result.get("context", []) # Get the retrieved documents
        logger.debug(f"Retrieved {len(retrieved_docs)} documents for the hint.")

        logger.info(f"Generated hint: {generated_hint[:100]}...")
        return generated_hint

    except Exception as e:
        logger.exception(f"Error generating RAG hint: {e}")
        # Consider checking for specific error types if needed
        return "There was an error while trying to generate a hint for you. Please try again."

# --- Optional: Function to explicitly trigger initialization during startup (No changes needed) ---
def ensure_rag_components_initialized():
    """Public function to trigger initialization, e.g., during app startup."""
    if _rag_chain_with_source is None:
        if not _initialize_rag_components():
             raise RuntimeError("Failed to initialize critical RAG components during startup check.")
        else:
             logger.info("RAG components initialized successfully during startup check.")
    else:
        logger.info("RAG components already initialized.")