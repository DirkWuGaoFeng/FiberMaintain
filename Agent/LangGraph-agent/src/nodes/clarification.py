"""
Clarification Node — Parameter incomplete, ask user for more info.

Uses LangGraph native interrupt() to pause graph execution.
User reply resumes via Command(goto="rule_engine").

Advantages:
- State persisted by Checkpointer, survives service restart
- On resume, skips input_guard (already validated)
- User reply can also hit rule engine
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def clarification_node(state: MainGraphState) -> dict:
    """
    Clarification node: ask user to provide missing parameters.

    When ParamGate detects parse_failures, this node generates
    a helpful clarification message with examples.
    """
    params = state.get("normalized_params", {})
    failures = params.get("parse_failures", [])

    # Build clarification message
    question_parts = ["抱歉，以下信息我没能正确识别：\n"]
    for f in failures:
        question_parts.append(f"  • {f}")
    question_parts.append("\n请补充说明，例如：")
    question_parts.append("  • 光纤编号：FIB-0012 或 12号光纤")
    question_parts.append("  • 单盘端口：5号盘3口")
    question_parts.append("  • 颜色：红色 / 黄色")
    question_parts.append("  • 时间：最近一周 / 7月22日到29日")

    clarification_msg = "\n".join(question_parts)

    logger.info(f"[Clarification] Asking user: {len(failures)} failures")

    # For MVP: return clarification as final output
    # In production with interrupt support, would use:
    #   user_reply = interrupt({"question": clarification_msg})
    #   return Command(goto="rule_engine", update={"user_input": user_reply})
    return {
        "messages": [AIMessage(content=clarification_msg)],
        "final_output": clarification_msg,
        "processing_path": "normal",
    }
