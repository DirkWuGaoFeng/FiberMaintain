"""
结果聚合节点 —— 最终输出组装。

【功能说明】
收集所有路径（快速路径、正常路径、报告、知识、批量）的结果，
生成给用户的最终回复。

【优先级顺序】
1. final_output（已由上游节点设置）
2. fast_path_result（快速路径已完成）
3. report_content（报告生成器输出）
4. batch_results（批量查询结果）
5. rag_context（知识问答结果）
6. 最后一条 AI 消息
7. 兆底消息

【面试知识点】
  Q: 为什么需要结果聚合器而不是直接输出？
  A: 系统有多条执行路径（快速/正常/报告/批量/知识），
     需要一个统一的出口来组装最终响应，简化前端处理逻辑。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..context.task_context import _derive_completed_steps
from ..graph.state import MainGraphState
from ..memory.user_memory import get_user_memory_manager
from ..security.output_filter import output_filter

logger = logging.getLogger(__name__)


async def result_aggregator_node(state: MainGraphState) -> dict:
    """结果聚合节点：从各路径组装最终输出。

    【优先级】
    1. final_output → 2. fast_path_result → 3. report_content
    4. batch_results → 5. rag_context → 6. 最后AI消息 → 7. 兆底

    【任务上下文 [v7.2]】终节点统一回写已完成步骤。

    【输出护栏 [v7.4]】所有最终输出统一经 output_filter 脱敏
    （IP 掩码/错误详情隐藏），防止内部信息外泄到前端。

    【用户记忆 [v7.4]】有 user_id 时注入输出格式/语言偏好，
    零 LLM 开销；无 user_id 时静默跳过（不改变默认行为）。
    """
    # 已完成步骤（代码派生），写入最终状态
    progress = _derive_completed_steps(state)

    # 用户记忆偏好注入（仅当 state 提供 user_id；缺失时跳过不报错）
    user_prefs: dict = {}
    user_id = state.get("user_id") or ""
    if user_id:
        try:
            user_prefs = get_user_memory_manager().inject_preferences(user_id, {})
            # [P0-2] 用户记忆语义检索：按当前问题召回相关历史事件，
            # 与偏好一起注入（书籍 Ch3 双层记忆：概览=偏好, 细节=事件）
            related_events = await _retrieve_user_events(user_id, state.get("user_input", ""))
            if related_events:
                user_prefs["memory_events"] = related_events
        except Exception as e:
            logger.warning(f"[ResultAggregator] UserMemory inject failed: {e}")

    def _sanitize(text: str) -> str:
        """统一输出脱敏（角色默认 operator）。"""
        return output_filter.filter(text or "")

    def _with_progress(updates: dict, *, messages: list | None = None) -> dict:
        updates["task_progress"] = progress
        if "final_output" in updates:
            updates["final_output"] = _sanitize(updates["final_output"])
        if messages:
            updates["messages"] = messages
        if user_prefs:
            updates["user_preferences"] = user_prefs
        return updates

    # 已有上游节点设置的最终输出，直接传递
    if state.get("final_output"):
        return _with_progress({"final_output": state["final_output"]})

    # 检查快速路径结果
    if state.get("fast_path_result"):
        return _with_progress({"final_output": state["fast_path_result"]})

    # 检查报告内容
    if state.get("report_content"):
        return _with_progress(
            {
                "messages": [AIMessage(content=_sanitize(state["report_content"]))],
                "final_output": state["report_content"],
            }
        )

    # 检查批量查询结果
    batch_results = state.get("batch_results", [])
    if batch_results:
        summary = _summarize_batch(batch_results)
        return _with_progress(
            {
                "messages": [AIMessage(content=_sanitize(summary))],
                "final_output": summary,
            }
        )

    # 检查 RAG 知识片段（知识问答）
    rag_context = state.get("rag_context", [])
    if rag_context:
        answer = "\n".join(rag_context[:3])
        return _with_progress(
            {
                "messages": [AIMessage(content=_sanitize(answer))],
                "final_output": answer,
            }
        )

    # 兆底：使用最后一条 AI 消息
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.type == "ai" and msg.content:
            return _with_progress({"final_output": msg.content})

    # 最终兆底
    fallback = "抱歉，我暂时无法处理您的请求。请稍后重试。"
    return _with_progress(
        {
            "messages": [AIMessage(content=_sanitize(fallback))],
            "final_output": fallback,
        }
    )


def _summarize_batch(results: list[dict]) -> str:
    """汇总批量查询结果，生成摘要文本。"""
    total = len(results)
    errors = sum(1 for r in results if r.get("error"))
    success = total - errors

    lines = [f"📊 批量查询完成：共 {total} 条，成功 {success} 条"]
    if errors:
        lines.append(f"  失败 {errors} 条")

    # 颜色分布统计（如有）
    colors = {}
    for r in results:
        color = r.get("color", "UNKNOWN")
        colors[color] = colors.get(color, 0) + 1
    if colors:
        color_str = "、".join(f"{k}: {v}" for k, v in colors.items())
        lines.append(f"  颜色分布：{color_str}")

    return "\n".join(lines)


async def _retrieve_user_events(user_id: str, query_text: str) -> list[dict]:
    """[P0-2] 按当前用户问题语义检索用户历史事件（书籍 Ch3 双层记忆细节层）.

    返回检索到的事件列表（含 event_type / details / similarity）；
    检索器不可用或异常时静默返回空（不阻塞主链路）。
    """
    if not query_text:
        return []
    try:
        from ..memory.user_memory_retriever import get_user_memory_retriever

        events = await get_user_memory_retriever().query_hybrid(user_id, query_text, top_k=3)
        return [
            {
                "event_type": e.get("event_type", ""),
                "details": e.get("details", {}),
                "similarity": e.get("similarity", 0.0),
            }
            for e in events
        ]
    except Exception as e:  # noqa: BLE001 - memory must never break aggregation
        logger.warning(f"[ResultAggregator] User event retrieval failed: {e}")
        return []
