# app/utils/config.py
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env file before defining settings
load_dotenv(override=True)

class Settings(BaseSettings):
    # PDF and ChromaDB Settings
    pdf_path: str = "evaluation/data/evaluation_source.pdf" 
    QUESTION_CSV_FILE_PATH: str = "evaluation/data/server_ready_questions.csv" 

    # pdf_path: str = "data/source_material.pdf"
    # QUESTION_CSV_FILE_PATH: str =  "data/questions.csv"

    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_name: str = "ai_tutor_collection"
    embedding_model_name: str = 'all-MiniLM-L6-v2'
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_k: int = 3
    hf_cache_dir: str = "./chroma_db/hf_cache" # Directory for Hugging Face cache
    log_level: str = os.getenv("LOG_LEVEL", "DEBUG").upper()

    # general LLM config
    max_output_tokens: int = 100 # for test

    # --- LLM Provider Configuration ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()

    # Ollama specific
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "mistral") # Default if not in .env

    # OpenAI specific
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model_name: str = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")

    # Google Gemini specific
    google_api_key: str | None = os.getenv("GOOGLE_API_KEY")
    google_model_name: str = os.getenv("GOOGLE_MODEL_NAME", "gemini-1.5-flash-latest")

    # AWS Bedrock specific 
    aws_access_key_id: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region_name: str | None = os.getenv("AWS_REGION_NAME")
    bedrock_model_id: str | None = os.getenv("BEDROCK_MODEL_ID")

    # BKT Parameters (Stage 3)
    bkt_p_l0: float = 0.2  # Prior prob of knowing skill
    bkt_p_t: float = 0.15  # Prob of transitioning from not known to known
    bkt_p_g: float = 0.2  # Prob of guessing correctly
    bkt_p_s: float = 0.1   # Prob of slipping (knowing but answering wrong)

    # Intervention Controller Thresholds (Stage 3)
    intervention_mastery_threshold: float = 0.15
    intervention_max_consecutive_errors: int = 2
    intervention_max_consecutive_skips: int = 1 # show hint if question was skipped
    intervention_time_limit_ms: int = 10000 # 10 seconds

    # Personalization Settings (Stage 4.5)
    exploration_rate: float = 0.2  # 20% chance to explore a random hint style (plus the adaptive count of available feedbacks)
    warmup_exploration_rate: float = 0.8 # 80% chance to explore in the first 5 questions
    feedback_rating_weight: float = 0.7 # Weight of explicit user rating in effectiveness score

    # --- Database Settings (Stage 5) ---
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/aitutor_db")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

settings = Settings()

# --- Validation for API keys based on provider ---
if settings.llm_provider == "openai" and not settings.openai_api_key:
    raise ValueError("LLM_PROVIDER is 'openai' but OPENAI_API_KEY is not set in .env")
if settings.llm_provider == "google" and not settings.google_api_key:
    raise ValueError("LLM_PROVIDER is 'google' but GOOGLE_API_KEY is not set in .env")
if settings.llm_provider == "bedrock" and not settings.bedrock_model_id:
    raise ValueError("LLM_PROVIDER is 'bedrock' but BEDROCK_MODEL_ID is not set in .env")
# Add similar checks for Bedrock if implemented
