"""
RAG 工具集 —— 通过 ChromaDB + BM25 混合检索实现知识库检索。

这些工具由 report_generator 和 knowledge_assistant 子图使用。
它们在本地对 ChromaDB 向量库执行检索（不访问 C++ 后端）。
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 延迟初始化的检索器（通过 init_rag_tools 设置）
_retriever = None


def init_rag_tools(retriever) -> None:
    """使用共享的检索器实例初始化 RAG 工具。"""
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
    """检索光纤维护知识库，返回最相关的前 3 条知识片段。
    分类：device_manual、maintenance_guide、alarm_guide、fault_cases、threshold_standard、ne_config。"""
    if _retriever is None:
        return json.dumps({"error": "RAG retriever not initialized", "results": []})

    try:
        docs = await _retriever.ainvoke(query)
        results = []
        for doc in docs[:3]:
            results.append(
                {
                    "content": doc.page_content[:500],
                    "source": doc.metadata.get("source", "unknown"),
                    "category": doc.metadata.get("category", "general"),
                    "score": doc.metadata.get("relevance_score", 0),
                }
            )
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[RAG] Query failed: {e}")
        return json.dumps({"error": str(e), "results": []})


@tool(args_schema=RAGSearchInput)
async def rag_search(query: str, top_k: int = 3) -> str:
    """检索知识库，结果数量可配置。
    返回：知识片段（含内容与来源）的 JSON 数组。"""
    if _retriever is None:
        return json.dumps({"error": "RAG retriever not initialized", "results": []})

    try:
        docs = await _retriever.ainvoke(query)
        results = []
        for doc in docs[:top_k]:
            results.append(
                {
                    "content": doc.page_content[:800],
                    "source": doc.metadata.get("source", "unknown"),
                    "category": doc.metadata.get("category", "general"),
                }
            )
        return json.dumps(results, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[RAG] Search failed: {e}")
        return json.dumps({"error": str(e), "results": []})
