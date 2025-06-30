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

# --- Global variables for initialized components (initialized lazily) ---
_embedding_function = None
_vectorstore = None
_retriever = None
_llm_client = None
_rag_chain_with_source = None
_init_lock = threading.Lock()


# --- Updated Prompt Template ---
# Explicitly structure the information for the LLM
template = """
**Instructions:** You are an AI Tutor. Your goal is to provide a helpful hint to a student based on their question and their answer attempt, using the provided context. Focus on clarifying the core concept without giving away the direct answer. If the context isn't relevant, acknowledge that and offer general advice related to the question's topic. Keep the hint concise, encouraging, and focused.

**Hint Style:** {hint_style}

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
    global _embedding_function, _vectorstore, _retriever, _llm_client, _rag_chain_with_source

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
            if _llm_client is None:
                logger.info(f"Initializing LLM client for provider: {settings.llm_provider}")
                provider = settings.llm_provider
                if provider == "ollama":
                    _llm_client = Ollama(
                        base_url=settings.ollama_base_url,
                        model=settings.ollama_model
                    )
                    logger.info(f"Initialized Ollama with model: {settings.ollama_model}")
                elif provider == "openai":
                    _llm_client = ChatOpenAI(
                        openai_api_key=settings.openai_api_key,
                        model_name=settings.openai_model_name,
                        temperature=0 # Adjust temperature as needed
                    )
                    logger.info(f"Initialized OpenAI with model: {settings.openai_model_name}")
                elif provider == "google":
                    _llm_client = ChatGoogleGenerativeAI(
                        google_api_key=settings.google_api_key,
                        model=settings.google_model_name,
                        temperature=0, # Adjust temperature as needed
                        convert_system_message_to_human=True # Often needed for Gemini
                    )
                    logger.info(f"Initialized Google Gemini with model: {settings.google_model_name}")
                # elif provider == "bedrock": # Add Bedrock logic if needed
                #     # Ensure boto3 is installed and AWS credentials are configured
                #     # (via .env, standard AWS config files, or IAM role)
                #     _llm_client = BedrockChat(
                #         # credentials_profile_name="your-aws-profile", # Optional profile
                #         region_name=settings.aws_region_name,
                #         model_id=settings.bedrock_model_id,
                #         model_kwargs={"temperature": 0.1} # Example model kwarg
                #     )
                #     logger.info(f"Initialized AWS Bedrock with model ID: {settings.bedrock_model_id}")
                else:
                    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

                # Optional: Add a check here to ensure the LLM client is working (e.g., dummy invoke)


            # 4. Define RAG Chain (Revised Logic)
            if _retriever and _llm_client and rag_prompt:
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
                              | _llm_client  # Call the LLM
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
async def get_rag_hint(question_text: str, user_answer: str | None, user_id: str) -> dict:
    """
    Retrieves context, gets adaptive hint style, and generates a personalized hint.
    Returns a dictionary containing the hint and the style used.
    """
    global _rag_chain_with_source

    if _rag_chain_with_source is None:
        if not _initialize_rag_components():
            logger.error("RAG components failed to initialize. Cannot generate hint.")
            return {
                "hint": "Sorry, the AI Tutor components could not be initialized. Please contact support.",
                "hint_style": "error"
            }

    try:
        # Get the adaptively chosen hint style for the user
        hint_style = personalization_service.get_adaptive_hint_style(user_id)
        logger.info(f"Generating RAG hint for user {user_id} with style: '{hint_style}' (Provider: {settings.llm_provider})")

        input_data = {
            "question": question_text,
            "user_answer": user_answer,
            "hint_style": hint_style
        }

        # Invoke the RAG chain
        result = await _rag_chain_with_source.ainvoke(input_data)

        generated_hint = result.get("answer", "Sorry, I couldn't generate a hint based on the available information.")
        logger.info(f"Generated hint: {generated_hint[:100]}...")

        return {"hint": generated_hint, "hint_style": hint_style}

    except Exception as e:
        logger.exception(f"Error generating RAG hint for user {user_id}: {e}")
        return {
            "hint": "There was an error while trying to generate a hint for you. Please try again.",
            "hint_style": "error"
        }

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