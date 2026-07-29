"""
Knowledge base ingestion: load documents into ChromaDB vector store.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def ingest_knowledge_base(kb_dir: str = "", persist_dir: str = "") -> int:
    """
    Ingest knowledge base documents into ChromaDB.

    Args:
        kb_dir: Knowledge base directory (default: knowledge_base/)
        persist_dir: ChromaDB persist directory

    Returns:
        Number of documents ingested
    """
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from .embeddings import get_embeddings

    kb_dir = kb_dir or os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base")
    persist_dir = persist_dir or os.environ.get("CHROMA_PERSIST_DIR", "data/chromadb")

    embeddings = get_embeddings()
    vectorstore = Chroma(
        collection_name="fiber_knowledge",
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )

    docs = []
    if os.path.exists(kb_dir):
        for filename in os.listdir(kb_dir):
            filepath = os.path.join(kb_dir, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    category = _infer_category(filename)
                    # Split large documents into chunks
                    chunks = _chunk_document(content, chunk_size=500, overlap=50)
                    for i, chunk in enumerate(chunks):
                        docs.append(Document(
                            page_content=chunk,
                            metadata={
                                "source": filename,
                                "category": category,
                                "chunk_index": i,
                            },
                        ))
                except Exception as e:
                    logger.warning(f"[Ingest] Failed to load {filename}: {e}")

    if docs:
        vectorstore.add_documents(docs)
        logger.info(f"[Ingest] Added {len(docs)} document chunks to ChromaDB")
    else:
        logger.warning("[Ingest] No documents found in knowledge base")

    return len(docs)


def _chunk_document(content: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split a document into overlapping chunks."""
    if len(content) <= chunk_size:
        return [content]

    chunks = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunk = content[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks


def _infer_category(filename: str) -> str:
    """Infer knowledge category from filename."""
    name = filename.lower()
    if "device" in name or "board" in name:
        return "device_manual"
    elif "maintenance" in name or "guide" in name:
        return "maintenance_guide"
    elif "alarm" in name:
        return "alarm_guide"
    elif "fault" in name or "case" in name:
        return "fault_cases"
    elif "threshold" in name or "standard" in name:
        return "threshold_standard"
    elif "ne" in name or "config" in name:
        return "ne_config"
    return "general"
