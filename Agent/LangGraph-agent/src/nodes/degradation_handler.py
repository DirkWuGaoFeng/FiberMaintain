"""
降级处理节点 —— 服务故障时的优雅降级策略。

【功能说明】
处理 L3（无 LLM）和 L4（后端离线）级别的降级：
- L3：保留工具查询 + 规则模板输出（不经过 LLM）
- L4：本地缓存 + 纯 RAG + 明确通知用户

【降级等级】
- L0：正常（无降级）
- L1/L2：简化输出（部分功能受限）
- L3：无 LLM（仅规则引擎 + 模板）
- L4：后端离线（仅缓存 + 知识问答）

【面试知识点】
  Q: 为什么需要降级机制？
  A: 工业级系统必须保证“部分可用”而非“全有或全无”。
     即使 LLM 服务宕机，规则引擎仍能提供基础查询服务。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def degradation_handler_node(state: MainGraphState) -> dict:
    """降级处理节点：在正常路径不可用时生成降级输出。

    【功能说明】
    根据降级等级选择不同策略：
    - L4：后端离线，尝试缓存数据
    - L3：无 LLM，使用规则模板输出
    - L1/L2：简化输出（含完整分析数据）

    【输入】state.degradation_level, state.rule_judgment
    【输出】final_output（降级输出文本）
    【状态更新】processing_path="degraded"
    """
    level = state.get("degradation_level", 0)
    judgment = state.get("rule_judgment")
    data_summary = state.get("collected_data_summary", "")

    if level >= 4:
        # L4：后端离线，尝试缓存
        output = _handle_l4_offline(state)
    elif level >= 3:
        # L3：无 LLM 可用，使用模板
        output = _handle_l3_no_llm(judgment, data_summary)
    else:
        # L1/L2: 使用完整分析数据输出
        output = _handle_simplified(state, judgment, data_summary)

    return {
        "messages": [AIMessage(content=output)],
        "final_output": output,
        "processing_path": "degraded",
    }


def _handle_l3_no_llm(judgment: dict | None, data_summary: str) -> str:
    """L3 降级：无 LLM，使用规则模板输出。

    【功能说明】
    直接使用 RuleJudgment 的结构化数据生成文本，不经过 LLM 美化。
    用户看到的是规则引擎的原始判断结果。
    """
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
    """L4 降级：后端离线，提供缓存数据（如可用）。"""
    return (
        "⚠️ 后端服务当前离线。\n"
        "  • 实时数据查询暂不可用\n"
        "  • 知识问答功能正常\n"
        "  • 请稍后重试或联系管理员\n"
        "\n（系统将在后端恢复后自动切回正常模式）"
    )


def _handle_simplified(state: MainGraphState, judgment: dict | None, data_summary: str) -> str:
    """L1/L2 降级：使用可用数据生成完整分析输出。

    【功能说明】
    利用 RuleJudgment 的结构化数据（状态、发现、指标、建议）
    生成包含完整分析结论的输出，而非仅列出发现。
    """
    if judgment:
        status = judgment.get("status", "UNKNOWN")
        findings = judgment.get("findings", [])
        metrics = judgment.get("metrics", {})
        actions = judgment.get("suggested_actions", [])

        # 从状态中提取光纤 ID（如果有）
        params = state.get("normalized_params", {})
        fiber_ids = params.get("fiber_ids", [])
        fiber_label = f"光纤{fiber_ids[0]}" if fiber_ids else "光纤"

        # 严重程度 emoji
        status_emoji = {"NORMAL": "✅", "WARNING": "⚡", "CRITICAL": "⚠️"}.get(status, "📊")
        status_cn = {"NORMAL": "正常", "WARNING": "告警", "CRITICAL": "严重"}.get(status, status)

        lines = [f"{status_emoji} {fiber_label}分析结论：{status_cn}"]
        lines.append("")

        # 关键指标
        if metrics:
            lines.append("📈 关键指标：")
            if "spanloss" in metrics:
                sl = metrics["spanloss"]
                # 自动标注衰耗状态
                if sl > 8.0:
                    lines.append(f"  • 跨段衰耗：{sl}dB ⚠️ 严重超标")
                elif sl > 5.0:
                    lines.append(f"  • 跨段衰耗：{sl}dB ⚡ 超过阈值")
                else:
                    lines.append(f"  • 跨段衰耗：{sl}dB ✅ 正常")
            if "oop" in metrics:
                lines.append(f"  • 输出光功率(OOP)：{metrics['oop']}dBm")
            if "iop" in metrics:
                lines.append(f"  • 输入光功率(IOP)：{metrics['iop']}dBm")
            lines.append("")

        # 告警级别
        alarm_lines = []
        if metrics.get("alarm_critical", 0) > 0:
            alarm_lines.append(f"  • CRITICAL（严重）：{metrics['alarm_critical']} 条")
        if metrics.get("alarm_major", 0) > 0:
            alarm_lines.append(f"  • MAJOR（主要）：{metrics['alarm_major']} 条")
        if metrics.get("alarm_minor", 0) > 0:
            alarm_lines.append(f"  • MINOR（次要）：{metrics['alarm_minor']} 条")
        if alarm_lines:
            lines.append("🚨 告警级别：")
            lines.extend(alarm_lines)
            lines.append("")

        # 分析发现
        if findings:
            lines.append("🔍 分析发现：")
            for f in findings:
                lines.append(f"  • {f}")
            lines.append("")

        # 建议措施
        if actions:
            lines.append("💡 建议措施：")
            for i, action in enumerate(actions, 1):
                lines.append(f"  {i}. {action}")

        return "\n".join(lines)

    if data_summary:
        return f"📋 查询结果：\n{data_summary[:500]}"

    return "处理完成，但未能获取详细分析。请稍后重试。"
