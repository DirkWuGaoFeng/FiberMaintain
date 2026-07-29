"""
Hybrid retriever: ChromaDB vector search + BM25 keyword search.

Implements EnsembleRetriever with weights [0.6, 0.4] (vector:keyword).
Optional Reranker for improved precision.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8100"))
CHROMA_PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", "data/chromadb")


def build_retriever():
    """
    Build the hybrid retriever: Vector (ChromaDB) + BM25 -> EnsembleRetriever.

    Returns:
        EnsembleRetriever or None if dependencies not available
    """
    try:
        from langchain_chroma import Chroma
        from langchain.retrievers import EnsembleRetriever
        from .embeddings import get_embeddings

        embeddings = get_embeddings()

        # Vector retriever (ChromaDB)
        vectorstore = Chroma(
            collection_name="fiber_knowledge",
            embedding_function=embeddings,
            persist_directory=CHROMA_PERSIST_DIR,
        )
        vector_retriever = vectorstore.as_retriever(
            search_kwargs={"k": 5}
        )

        # For BM25, we need documents loaded
        # In production, documents are loaded from knowledge_base/ directory
        try:
            from langchain_community.retrievers import BM25Retriever
            from langchain_core.documents import Document

            # Load documents from knowledge base
            docs = _load_knowledge_base_docs()
            if docs:
                bm25_retriever = BM25Retriever.from_documents(docs, k=5)
                # Hybrid retrieval
                return EnsembleRetriever(
                    retrievers=[vector_retriever, bm25_retriever],
                    weights=[0.6, 0.4],
                )
        except ImportError:
            logger.warning("BM25Retriever not available, using vector-only retrieval")

        return vector_retriever

    except Exception as e:
        logger.error(f"[RAG] Failed to build retriever: {e}")
        return None


def _load_knowledge_base_docs():
    """Load documents from the knowledge_base/ directory."""
    from langchain_core.documents import Document
    import os

    kb_dir = os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base")
    docs = []

    if not os.path.exists(kb_dir):
        return docs

    for filename in os.listdir(kb_dir):
        filepath = os.path.join(kb_dir, filename)
        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Determine category from filename
                category = _infer_category(filename)
                docs.append(Document(
                    page_content=content,
                    metadata={"source": filename, "category": category},
                ))
            except Exception as e:
                logger.warning(f"[RAG] Failed to load {filename}: {e}")

    return docs


def _infer_category(filename: str) -> str:
    """Infer knowledge category from filename."""
    name = filename.lower()
    if "device" in name or "manual" in name or "board" in name:
        return "device_manual"
    elif "maintenance" in name or "guide" in name or "patrol" in name:
        return "maintenance_guide"
    elif "alarm" in name:
        return "alarm_guide"
    elif "fault" in name or "case" in name:
        return "fault_cases"
    elif "threshold" in name or "standard" in name:
        return "threshold_standard"
    elif "ne" in name or "config" in name or "topology" in name:
        return "ne_config"
    return "general"
