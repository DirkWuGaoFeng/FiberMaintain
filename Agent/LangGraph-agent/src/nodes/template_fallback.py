"""
模板兆底节点 [v7.1] —— 叙述校验失败时的零 LLM 输出。

【功能说明】
当叙述校验器检测到数据篡改时，此节点直接从 RuleJudgment 数据
生成结构化响应。以数据准确性为优先，牺牲一定的自然语言流畅性。

【设计原则】
- 数据准确性 > 语言流畅性
- 不经过 LLM，纯模板渲染
- 明确告知用户“本回复由模板引擎生成”

【面试知识点】
  Q: 为什么叫“兆底”？
  A: 这是系统的最后一道防线，当 LLM 叙述失败时，保证用户至少能
     看到准确的结构化数据，而不是空白或错误信息。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def template_fallback_node(state: MainGraphState) -> dict:
    """模板兆底节点：不经过 LLM 生成结构化响应。

    【使用场景】
    当叙述校验失败时（数据完整性 > 流畅性），使用此节点。
    直接从 RuleJudgment 提取状态、发现、指标、建议生成文本。

    【输入】state.rule_judgment（RuleJudgment 序列化）
    【输出】final_output（模板生成的结构化文本）
    """
    judgment = state.get("rule_judgment")

    if not judgment:
        msg = "分析结果暂不可用。"
        return {
            "messages": [AIMessage(content=msg)],
            "final_output": msg,
        }

    status = judgment.get("status", "UNKNOWN")
    findings = judgment.get("findings", [])
    metrics = judgment.get("metrics", {})
    actions = judgment.get("suggested_actions", [])

    # 构建结构化模板响应
    status_emoji = {"NORMAL": "✅", "WARNING": "⚡", "CRITICAL": "⚠️"}.get(status, "📊")
    lines = [f"{status_emoji} 光纤状态：{status}"]

    for f in findings:
        lines.append(f"  • {f}")

    if metrics:
        metrics_parts = []
        if "spanloss" in metrics:
            metrics_parts.append(f"衰耗 {metrics['spanloss']}dB")
        if "oop" in metrics:
            metrics_parts.append(f"OOP {metrics['oop']}dBm")
        if "iop" in metrics:
            metrics_parts.append(f"IOP {metrics['iop']}dBm")
        if metrics_parts:
            lines.append(f"📈 关键指标：{'，'.join(metrics_parts)}")

    if actions:
        lines.append(f"💡 建议：{'；'.join(actions)}")

    lines.append("\n⚠️ （本回复由模板引擎生成，自然语言表述暂不可用）")

    output = "\n".join(lines)
    logger.info("[TemplateFallback] Generated template response")

    return {
        "messages": [AIMessage(content=output)],
        "final_output": output,
    }
