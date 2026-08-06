"""
Knowledge Assistant Node — RAG retrieval + LLM answer [v7.1].

Flow: Query Rewrite (optional) → Hybrid Retrieve → LLM Generate (7b)

Receives from MainGraphState:
- user_input: the knowledge question
- rag_context: pre-retrieved context (if any)

Returns:
- final_output: knowledge answer
- messages: AIMessage with answer
- rag_context: retrieved chunks
- llm_call_count: incremented
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from ...graph.state import MainGraphState
from ...llm.provider import get_knowledge_llm

logger = logging.getLogger(__name__)

# =============================================================================
# Knowledge QA Prompt
# =============================================================================

KNOWLEDGE_QA_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是光纤维护知识库助手。根据提供的知识库内容回答用户问题。

## 规则
1. 仅基于提供的知识库内容回答，不得编造
2. 如果知识库中没有相关信息，明确告知用户
3. 引用具体的知识点来源
4. 语言简洁专业，适合运维人员阅读
5. 涉及操作步骤时，给出清晰的步骤列表"""),
    ("human", """## 知识库参考内容
{rag_context}

## 用户问题
{question}

请基于知识库内容回答。如果知识库中没有相关信息，请明确说明。"""),
])

# Fallback answer when no context and no LLM
_NO_KNOWLEDGE_MSG = (
    "抱歉，当前知识库中未找到与您问题相关的内容。\n"
    "建议您：\n"
    "1. 尝试更具体的关键词（如'OTDR测试步骤'、'光纤衰耗标准'）\n"
    "2. 联系管理员确认知识库是否已更新\n"
    "3. 查阅设备厂商提供的操作手册"
)


async def _retrieve_knowledge(query: str) -> list[str]:
    """
    Attempt RAG retrieval from knowledge engine.

    Returns list of relevant text chunks. Empty list if RAG unavailable.
    """
    try:
        from ...rag.engine import get_rag_engine

        engine = get_rag_engine()
        if engine is None:
            return []

        results = await engine.retrieve(query, top_k=5)
        return [doc.get("content", "") for doc in results if doc.get("content")]
    except ImportError:
        logger.debug("[KnowledgeQA] RAG engine not available yet")
        return []
    except Exception as e:
        logger.warning(f"[KnowledgeQA] RAG retrieval failed: {e}")
        return []


async def knowledge_assistant_subgraph(state: dict) -> dict:
    """
    Knowledge QA node: RAG retrieval + LLM answer generation.

    Uses qwen2.5:7b (Secondary) for answer generation.
    Falls back gracefully when RAG or LLM unavailable.
    """
    user_input = state.get("user_input", "")
    if not user_input:
        # Try to extract from messages
        messages = state.get("messages", [])
        if messages:
            last_msg = messages[-1]
            user_input = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    logger.info(f"[KnowledgeQA] Processing question: {user_input[:80]}")

    # Step 1: Retrieve knowledge context
    rag_context = state.get("rag_context", [])
    if not rag_context:
        rag_context = await _retrieve_knowledge(user_input)

    # Step 2: Generate answer
    if not rag_context:
        # No knowledge found — still try LLM for general answer
        context_text = "（知识库中未找到相关内容）"
    else:
        # Join top chunks
        context_text = "\n\n---\n\n".join(rag_context[:5])
        if len(context_text) > 3000:
            context_text = context_text[:3000] + "\n...(已截断)"

    try:
        llm = get_knowledge_llm()
        chain = KNOWLEDGE_QA_PROMPT | llm

        result = await chain.ainvoke({
            "rag_context": context_text,
            "question": user_input,
        })

        answer = result.content if hasattr(result, "content") else str(result)

        # If no RAG context and answer seems generic, add disclaimer
        if not rag_context and "未找到" not in answer:
            answer += "\n\n⚠️ 注意：以上回答未基于知识库，仅供参考。"

        logger.info(f"[KnowledgeQA] Answer generated: {len(answer)} chars")

        return {
            "messages": [AIMessage(content=answer)],
            "final_output": answer,
            "rag_context": rag_context,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
            "processing_path": "normal",
            "audit_trail": [{
                "node": "knowledge_qa",
                "action": "rag_answer",
                "chunks_used": len(rag_context),
                "answer_length": len(answer),
            }],
        }

    except Exception as e:
        logger.error(f"[KnowledgeQA] LLM generation failed: {e}")

        # L3 degradation: no LLM, return retrieval results directly
        if rag_context:
            fallback = f"📚 知识库检索结果（LLM 服务暂不可用）：\n\n{rag_context[0][:500]}"
        else:
            fallback = _NO_KNOWLEDGE_MSG

        return {
            "messages": [AIMessage(content=fallback)],
            "final_output": fallback,
            "rag_context": rag_context,
            "processing_path": "degraded",
            "audit_trail": [{
                "node": "knowledge_qa",
                "action": "error_fallback",
                "error": str(e),
            }],
        }
