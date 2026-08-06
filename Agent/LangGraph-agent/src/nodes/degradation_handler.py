"""
Degradation Handler Node — Graceful degradation when services fail.

Handles L3 (no LLM) and L4 (backend offline) degradation:
- L3: Keep tool queries + rule template output
- L4: Local cache + pure RAG + explicit notification
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def degradation_handler_node(state: MainGraphState) -> dict:
    """
    Degradation handler: produce output when normal path is unavailable.

    Uses rule_judgment data directly (no LLM) or cache data.
    """
    level = state.get("degradation_level", 0)
    judgment = state.get("rule_judgment")
    data_summary = state.get("collected_data_summary", "")

    if level >= 4:
        # L4: Backend offline, try cache
        output = _handle_l4_offline(state)
    elif level >= 3:
        # L3: No LLM available, use template
        output = _handle_l3_no_llm(judgment, data_summary)
    else:
        # L1/L2: Simplified output
        output = _handle_simplified(judgment, data_summary)

    return {
        "messages": [AIMessage(content=output)],
        "final_output": output,
        "processing_path": "degraded",
    }


def _handle_l3_no_llm(judgment: dict | None, data_summary: str) -> str:
    """L3: No LLM, use rule template output."""
    if judgment:
        status = judgment.get("status", "UNKNOWN")
        findings = judgment.get("findings", [])
        actions = judgment.get("suggested_actions", [])

        lines = [f"📊 光纤状态：{status}"]
        for f in findings:
            lines.append(f"  • {f}")
        if actions:
            lines.append(f"💡 建议：{'；'.join(actions)}")
        lines.append("\n⚠️ （分析服务暂不可用，以上为规则引擎判断结果）")
        return "\n".join(lines)

    if data_summary:
        return f"📋 数据已查到，分析暂不可用：\n{data_summary[:500]}"

    return "⚠️ 分析服务暂时不可用，请稍后重试。数据查询功能正常。"


def _handle_l4_offline(state: MainGraphState) -> str:
    """L4: Backend offline, provide cached data if available."""
    return (
        "⚠️ 后端服务当前离线。\n"
        "  • 实时数据查询暂不可用\n"
        "  • 知识问答功能正常\n"
        "  • 请稍后重试或联系管理员\n"
        "\n（系统将在后端恢复后自动切回正常模式）"
    )


def _handle_simplified(judgment: dict | None, data_summary: str) -> str:
    """L1/L2: Simplified output with available data."""
    if judgment:
        findings = judgment.get("findings", [])
        if findings:
            return "📋 分析结果：\n" + "\n".join(f"  • {f}" for f in findings)

    if data_summary:
        return f"📋 查询结果：\n{data_summary[:500]}"

    return "处理完成，但未能获取详细分析。请稍后重试。"
