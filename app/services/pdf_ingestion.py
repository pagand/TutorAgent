# Implements Oracle of Knowledge: PDF parsing using pdfminer.six, Langchain’s text splitting, Sentence Transformers for embeddings, and FAISS integration
# app/services/pdf_ingestion.py
import os
from langchain_community.document_loaders import PyMuPDFLoader # Or PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
# from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings as SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from app.utils.config import settings
from app.utils.logger import logger

# Ensure ChromaDB collection uses the same embedding function
embedding_function = SentenceTransformerEmbeddings(model_name=settings.embedding_model_name)

def ingest_pdf():
    """Loads, splits, embeds, and stores the PDF document in ChromaDB."""
    if not os.path.exists(settings.pdf_path):
        logger.error(f"PDF file not found at: {settings.pdf_path}")
        return

    # Check if ingestion has already happened (simple check)
    # A more robust check would query ChromaDB or use a status flag
    if os.path.exists(settings.chroma_persist_dir) and \
       os.path.exists(os.path.join(settings.chroma_persist_dir, 'chroma.sqlite3')): # DuckDB+parquet uses different structure
        try:
            # Try connecting to existing DB to see if collection exists
            vectorstore = Chroma(
                persist_directory=settings.chroma_persist_dir,
                collection_name=settings.chroma_collection_name,
                embedding_function=embedding_function,
            )
            # Simple check if collection likely has data
            if vectorstore._collection.count() > 0:
                 logger.info(f"Collection '{settings.chroma_collection_name}' already exists and seems populated. Skipping ingestion.")
                 return
        except Exception as e:
            logger.warning(f"Could not connect to existing ChromaDB or collection not found. Proceeding with ingestion. Error: {e}")
            # Clean up potentially corrupted persist directory if connection failed badly
            # import shutil
            # if os.path.exists(settings.chroma_persist_dir):
            #     shutil.rmtree(settings.chroma_persist_dir)


    logger.info(f"Starting ingestion for PDF: {settings.pdf_path}")
    try:
        # 1. Load PDF
        loader = PyMuPDFLoader(settings.pdf_path)
        documents = loader.load()
        logger.info(f"Loaded {len(documents)} pages from PDF.")

        if not documents:
            logger.error("No documents loaded from PDF. Aborting ingestion.")
            return

        # 2. Split Documents
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap
        )
        texts = text_splitter.split_documents(documents)
        logger.info(f"Split into {len(texts)} text chunks.")

        if not texts:
            logger.error("Document splitting resulted in zero chunks. Aborting ingestion.")
            return

        # 3. Embed and Store
        logger.info(f"Creating embeddings using '{settings.embedding_model_name}' and storing in ChromaDB at '{settings.chroma_persist_dir}'...")
        vectorstore = Chroma.from_documents(
            documents=texts,
            embedding=embedding_function,
            collection_name=settings.chroma_collection_name,
            persist_directory=settings.chroma_persist_dir
        )
        vectorstore.persist() # Persist the collection explicitly
        logger.info(f"Ingestion complete. Stored {len(texts)} chunks in collection '{settings.chroma_collection_name}'.")

    except Exception as e:
        logger.exception(f"An error occurred during PDF ingestion: {e}")

# You might run this function from a separate script or conditionally in main.py at startup
# Example main execution guard:
# if __name__ == "__main__":
#     ingest_pdf()
