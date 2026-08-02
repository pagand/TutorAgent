# app/services/pdf_ingestion.py
import os
from langchain_community.document_loaders import PyMuPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from app.utils.config import settings
from app.utils.logger import logger


def _make_embedding_function():
    return GoogleGenerativeAIEmbeddings(
        google_api_key=settings.google_api_key.get_secret_value() if settings.google_api_key else None,
        model=settings.google_embedding_model_name,
    )


def ingest_pdf():
    """Loads, splits, embeds, and stores the PDF document in ChromaDB."""
    if not os.path.exists(settings.pdf_path):
        logger.error(f"PDF file not found at: {settings.pdf_path}")
        return

    chroma_sqlite = os.path.join(settings.chroma_persist_dir, "chroma.sqlite3")
    if os.path.exists(chroma_sqlite):
        try:
            embedding_function = _make_embedding_function()
            vectorstore = Chroma(
                persist_directory=settings.chroma_persist_dir,
                collection_name=settings.chroma_collection_name,
                embedding_function=embedding_function,
            )
            if vectorstore._collection.count() > 0:
                logger.info(f"Collection '{settings.chroma_collection_name}' already populated. Skipping ingestion.")
                return
        except Exception as e:
            logger.warning(f"Could not verify existing ChromaDB collection: {e}. Re-ingesting.")

    logger.info(f"Starting ingestion for PDF: {settings.pdf_path}")
    try:
        loader = PyMuPDFLoader(settings.pdf_path)
        documents = loader.load()
        logger.info(f"Loaded {len(documents)} pages from PDF.")

        if not documents:
            logger.error("No documents loaded from PDF. Aborting ingestion.")
            return

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        texts = text_splitter.split_documents(documents)
        logger.info(f"Split into {len(texts)} text chunks.")

        if not texts:
            logger.error("Document splitting resulted in zero chunks. Aborting ingestion.")
            return

        embedding_function = _make_embedding_function()
        logger.info(f"Embedding and storing {len(texts)} chunks in ChromaDB at '{settings.chroma_persist_dir}'...")
        Chroma.from_documents(
            documents=texts,
            embedding=embedding_function,
            collection_name=settings.chroma_collection_name,
            persist_directory=settings.chroma_persist_dir,
        )
        logger.info(f"Ingestion complete. Stored {len(texts)} chunks in collection '{settings.chroma_collection_name}'.")

    except Exception as e:
        logger.exception(f"An error occurred during PDF ingestion: {e}")
