"""
Embeddings configuration for RAG retrieval.
"""

from __future__ import annotations

import os


def get_embeddings():
    """
    Get the embedding model for RAG.
    Uses a local HuggingFace model for offline operation.
    """
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name="BAAI/bge-large-zh-v1.5",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    except ImportError:
        # Fallback: use a simple hash-based embedding for testing
        from langchain_community.embeddings import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
