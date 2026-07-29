"""
RAG tools: knowledge base retrieval via ChromaDB + BM25 hybrid search.

These tools are used by report_generator and knowledge_assistant sub-graphs.
They operate locally against the ChromaDB vector store (not the C++ backend).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Lazy-initialized retriever (set via init_rag_tools)
_retriever = None


def init_rag_tools(retriever) -> None:
    """Initialize RAG tools with the shared retriever instance."""
    global _retriever
    _retriever = retriever


class RAGQueryInput(BaseModel):
    query: str = Field(description="Search query for knowledge base")
    category: str = Field(default="all", description="Knowledge category filter")


class RAGSearchInput(BaseModel):
    query: str = Field(description="Search query")
    top_k: int = Field(default=3, description="Number of results to return")


@tool(args_schema=RAGQueryInput)
async def rag_query(query: str, category: str = "all") -> str:
    """Search the fiber maintenance knowledge base, returns top 3 most relevant knowledge chunks.
    Categories: device_manual, maintenance_guide, alarm_guide, fault_cases, threshold_standard, ne_config."""
    if _retriever is None:
        return json.dumps({"error": "RAG retriever not initialized", "results": []})

    try:
        docs = await _retriever.ainvoke(query)
        results = []
        for doc in docs[:3]:
            results.append({
                "content": doc.page_content[:500],
                "source": doc.metadata.get("source", "unknown"),
                "category": doc.metadata.get("category", "general"),
                "score": doc.metadata.get("relevance_score", 0),
            })
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[RAG] Query failed: {e}")
        return json.dumps({"error": str(e), "results": []})


@tool(args_schema=RAGSearchInput)
async def rag_search(query: str, top_k: int = 3) -> str:
    """Search knowledge base with configurable result count.
    Returns: JSON array of knowledge chunks with content and source."""
    if _retriever is None:
        return json.dumps({"error": "RAG retriever not initialized", "results": []})

    try:
        docs = await _retriever.ainvoke(query)
        results = []
        for doc in docs[:top_k]:
            results.append({
                "content": doc.page_content[:800],
                "source": doc.metadata.get("source", "unknown"),
                "category": doc.metadata.get("category", "general"),
            })
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[RAG] Search failed: {e}")
        return json.dumps({"error": str(e), "results": []})
