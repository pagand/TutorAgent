# Database utilities to connect to ChromaDB (configured for vector operations)
# app/utils/db.py
from chromadb import Client
from chromadb.config import Settings

def get_db_connection():
    # Configure ChromaDB client
    client = Client(Settings(
        chroma_db_impl="duckdb+parquet",
        persist_directory="./chroma_db"  # Directory to store the database
    ))
    return client

