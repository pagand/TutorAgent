# Implements Oracle of Knowledge: PDF parsing using pdfminer.six, Langchain’s text splitting, Sentence Transformers for embeddings, and FAISS integration
# app/services/pdf_ingestion.py
from pdfminer.high_level import extract_text
from langchain.text_splitter import RecursiveCharacterTextSplitter

def parse_pdf(file_path: str) -> str:
    try:
        text = extract_text(file_path)
        return text
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        return ""

def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50):
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = splitter.split_text(text)
    return chunks

def get_pdf_chunks(file_path: str):
    text = parse_pdf(file_path)
    if text:
        return split_text(text)
    return []
