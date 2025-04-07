# app/utils/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    pdf_path: str = "data/source_material.pdf" # Path to your PDF Oracle
    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_name: str = "ai_tutor_collection"
    embedding_model_name: str = 'all-MiniLM-L6-v2'
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "phi3" 
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_k: int = 3 # Number of chunks to retrieve
    hf_cache_dir: str = "./chroma_db/hf_cache" # Directory for Hugging Face cache

    class Config:
        env_file = '.env' # Load sensitive keys from .env

settings = Settings()