"""
查询改写器 — 扩展用户查询以获得更好的 RAG 检索 [v7.1]。

使用 qwen2.5:7b（次级）结合领域关键词改写/扩展查询。
LLM 不可用时回退到原始查询。
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是光纤维护领域的查询改写专家。
将用户的简短问题改写为更适合知识库检索的查询。

## 规则
1. 保留原始意图，扩展专业术语
2. 添加同义词和相关概念
3. 输出不超过 100 字
4. 仅输出改写后的查询文本，不要解释

## 示例
输入: "光纤红了怎么办"
输出: "光纤颜色变为红色 RED 告警 处理步骤 故障排查 衰耗异常 紧急维护流程"

输入: "OTDR怎么测"
输出: "OTDR 光时域反射仪 测试方法 操作步骤 光纤断点定位 衰耗曲线分析""",
        ),
        ("human", "{query}"),
    ]
)

_chain = None


async def rewrite_query(query: str) -> str:
    """
    Rewrite user query for better retrieval.

    Args:
        query: Original user query

    Returns:
        Rewritten query (or original if rewriting fails)
    """
    global _chain

    # 已较详细的查询不再改写
    if len(query) > 80:
        return query

    try:
        if _chain is None:
            from ..llm.provider import get_query_rewriter_llm

            _chain = REWRITE_PROMPT | get_query_rewriter_llm()

        result = await _chain.ainvoke({"query": query})
        rewritten = result.content.strip() if hasattr(result, "content") else str(result).strip()

        # 合理性检查：改写结果应与原查询相关
        if len(rewritten) < 5 or len(rewritten) > 200:
            return query

        return rewritten
    except Exception as e:
        logger.debug(f"[QueryRewriter] Rewrite failed (using original): {e}")
        return query
