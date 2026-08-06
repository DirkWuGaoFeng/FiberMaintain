"""
Result Aggregator Node — Final output assembly.

Collects results from all paths (fast path, normal, report, knowledge, batch)
and produces the final response to the user.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def result_aggregator_node(state: MainGraphState) -> dict:
    """
    Result aggregator: assemble final output from various paths.

    Priority:
    1. fast_path_result (already complete)
    2. final_output (set by narrator/template/knowledge)
    3. report_content (from report generator)
    4. Last AI message in messages
    5. Fallback message
    """
    # Already have a final output from upstream nodes
    # Always pass through final_output so on_chain_end event carries it for frontend
    if state.get("final_output"):
        return {"final_output": state["final_output"]}

    # Check fast path result
    if state.get("fast_path_result"):
        return {"final_output": state["fast_path_result"]}

    # Check report content
    if state.get("report_content"):
        return {
            "messages": [AIMessage(content=state["report_content"])],
            "final_output": state["report_content"],
        }

    # Check batch results
    batch_results = state.get("batch_results", [])
    if batch_results:
        summary = _summarize_batch(batch_results)
        return {
            "messages": [AIMessage(content=summary)],
            "final_output": summary,
        }

    # Check RAG context (knowledge QA)
    rag_context = state.get("rag_context", [])
    if rag_context:
        answer = "\n".join(rag_context[:3])
        return {
            "messages": [AIMessage(content=answer)],
            "final_output": answer,
        }

    # Fallback: use last AI message
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.type == "ai" and msg.content:
            return {"final_output": msg.content}

    # Ultimate fallback
    fallback = "抱歉，我暂时无法处理您的请求。请稍后重试。"
    return {
        "messages": [AIMessage(content=fallback)],
        "final_output": fallback,
    }


def _summarize_batch(results: list[dict]) -> str:
    """Summarize batch query results."""
    total = len(results)
    errors = sum(1 for r in results if r.get("error"))
    success = total - errors

    lines = [f"📊 批量查询完成：共 {total} 条，成功 {success} 条"]
    if errors:
        lines.append(f"  失败 {errors} 条")

    # Color distribution if available
    colors = {}
    for r in results:
        color = r.get("color", "UNKNOWN")
        colors[color] = colors.get(color, 0) + 1
    if colors:
        color_str = "、".join(f"{k}: {v}" for k, v in colors.items())
        lines.append(f"  颜色分布：{color_str}")

    return "\n".join(lines)
