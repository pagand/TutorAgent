# app/utils/config.py
import os
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env file — shell env vars take precedence over .env values
load_dotenv()

class Settings(BaseSettings):
    # PDF and ChromaDB Settings
    # for test
    # pdf_path: str = "data/source_material.pdf"
    # QUESTION_CSV_FILE_PATH: str =  "data/questions.csv"

    # for eval
    # pdf_path: str = "evaluation/data/evaluation_source.pdf" 
    # QUESTION_CSV_FILE_PATH: str = "evaluation/data/server_ready_questions.csv" 
    
    # for Prod
    pdf_path: str = "prod/data/source.pdf" 
    QUESTION_CSV_FILE_PATH: str = "prod/data/server_ready_questions.csv" 

    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_name: str = "ai_tutor_collection"
    google_embedding_model_name: str = "models/gemini-embedding-001"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_k: int = 3
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # general LLM config
    max_output_tokens: int = 512
    use_llm_cache: bool = True  # env var: USE_LLM_CACHE

    # --- LLM Provider Configuration ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()

    # Ollama specific
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "mistral") # Default if not in .env

    # OpenAI specific
    openai_api_key: SecretStr | None = SecretStr(os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
    openai_model_name: str = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")

    # Google Gemini specific
    google_api_key: SecretStr | None = SecretStr(os.getenv("GOOGLE_API_KEY")) if os.getenv("GOOGLE_API_KEY") else None
    google_model_name: str = os.getenv("GOOGLE_MODEL_NAME", "gemini-2.5-flash-lite")

    # AWS Bedrock specific
    aws_access_key_id: SecretStr | None = SecretStr(os.getenv("AWS_ACCESS_KEY_ID")) if os.getenv("AWS_ACCESS_KEY_ID") else None
    aws_secret_access_key: SecretStr | None = SecretStr(os.getenv("AWS_SECRET_ACCESS_KEY")) if os.getenv("AWS_SECRET_ACCESS_KEY") else None
    aws_region_name: str | None = os.getenv("AWS_REGION_NAME")
    bedrock_model_id: str | None = os.getenv("BEDROCK_MODEL_ID")

    # --- API Key (Phase 3, Stage 2) ---
    # Obscurity, not secrecy: the frontend is a public static bundle, so
    # NEXT_PUBLIC_API_KEY is readable by anyone who opens devtools. This raises
    # the bar against drive-by scanning of the API during the exam window.
    # SecretStr so an accidental `logger.info(settings)` or unhandled traceback
    # can't print it in plain text.
    api_key: SecretStr | None = SecretStr(os.getenv("API_KEY")) if os.getenv("API_KEY") else None

    # BKT Parameters (Stage 3)
    bkt_p_l0: float = 0.2  # Prior prob of knowing skill
    bkt_p_t: float = 0.15  # Prob of transitioning from not known to known
    bkt_p_g: float = 0.2  # Prob of guessing correctly
    bkt_p_s: float = 0.1   # Prob of slipping (knowing but answering wrong)

    # Intervention Controller Thresholds (Stage 3)
    intervention_mastery_threshold: float = 0.20 # was 0.15
    intervention_max_consecutive_errors: int = 1
    intervention_max_consecutive_skips: int = 2 # show hint if question was skipped
    intervention_time_limit_ms: int = 30000 # 30 sec

    # Personalization Settings (Stage 4.5)
    exploration_rate: float = 0.2  # 20% chance to explore a random hint style (plus the adaptive count of available feedbacks)
    warmup_exploration_rate: float = 0.8 # 80% chance to explore in the first 5 questions
    feedback_rating_weight: float = 0.7 # Weight of explicit user rating in effectiveness score

    # --- Exam Timer Settings ---
    exam_duration_ms: int = int(os.getenv("EXAM_DURATION_MS", 25 * 60 * 1000))  # 25 minutes default

    # --- Database Settings (Stage 5) ---
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/aitutor_db")
    test_database_url: str = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

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
