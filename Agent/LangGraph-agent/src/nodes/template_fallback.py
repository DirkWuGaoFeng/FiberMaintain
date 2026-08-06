"""
Template Fallback Node [v7.1] — Zero-LLM output when Narrator validation fails.

When NarratorValidator detects data tampering, this node generates
a structured response directly from RuleJudgment data.
Guarantees data accuracy at the cost of natural language fluency.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def template_fallback_node(state: MainGraphState) -> dict:
    """
    Template fallback: generate structured response without LLM.

    Used when Narrator validation fails (data integrity > fluency).
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

    # Build structured template response
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
