"""
RAG Knowledge Engine [v7.1].

Components:
- engine.py: Main RAG engine (hybrid Vector + BM25 retrieval)
- query_rewriter.py: Query expansion using 7b LLM
- ingest.py: Document ingestion with term annotations
"""

from .engine import RAGEngine, get_rag_engine

__all__ = [
    "RAGEngine",
    "get_rag_engine",
]
