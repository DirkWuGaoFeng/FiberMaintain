"""
Input Guard Node — Security filter (Layer 1).

Performs prompt injection detection and input sanitization.
Zero LLM calls, pure regex + keyword matching, latency < 1ms.

[P0-B] Also applies the conversation sliding window: messages beyond
MESSAGE_WINDOW_SIZE are dropped so persisted threads cannot grow
unbounded (primary LLM is billed per token).
"""

from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from ..config import MAX_INPUT_LENGTH, MESSAGE_WINDOW_SIZE
from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)

# Prompt injection detection patterns (9 rules)
INJECTION_PATTERNS = [
    r"忽略(以上|之前|所有)[^，。!?！？]{0,6}(指令|提示|规则|设定)",
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
    r"你(现在|从现在起)是(?!.*光纤)",
    r"act\s+as\s+(if|though)",
    r"pretend\s+(you|to\s+be)",
    r"(system|系统)\s*prompt",
    r"删除(所有|全部|一切)(光纤|数据|记录|配置)",
    r"DROP\s+TABLE",
    r"<script",
]

# Compile patterns once at module load
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


async def input_guard_node(state: MainGraphState) -> dict:
    """
    Input security filter node.

    Checks:
    1. Prompt injection detection (regex patterns)
    2. Input length truncation (max 2000 chars)

    Returns:
        If blocked: messages with warning, processing_path="blocked"
        If passed: sanitized user_input
    """
    user_input = state.get("user_input", "")

    # Injection detection
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(user_input):
            logger.warning(f"[InputGuard] Injection detected: {user_input[:50]}...")
            return {
                "messages": [
                    AIMessage(content="⚠️ 检测到异常输入，已拦截。如有正常需求请重新描述。")
                ],
                "processing_path": "blocked",
                "final_output": "⚠️ 检测到异常输入，已拦截。如有正常需求请重新描述。",
            }

    # Length truncation
    if len(user_input) > MAX_INPUT_LENGTH:
        user_input = user_input[:MAX_INPUT_LENGTH]
        logger.info(f"[InputGuard] Input truncated to {MAX_INPUT_LENGTH} chars")

    updates: dict = {"user_input": user_input}

    # Sliding window [P0-B]: trim persisted history that exceeds the window.
    # messages uses the add_messages reducer, so trimming must emit
    # RemoveMessage ops (plain list return would APPEND, not replace).
    # The current turn's HumanMessage is upserted by id to carry the
    # sanitized content.
    messages = state.get("messages") or []
    if messages and len(messages) > MESSAGE_WINDOW_SIZE:
        to_remove = messages[:-MESSAGE_WINDOW_SIZE]
        new_messages: list = [RemoveMessage(id=m.id) for m in to_remove if m.id]
        current = messages[-1]
        if current.id:
            new_messages.append(HumanMessage(content=user_input, id=current.id))
        updates["messages"] = new_messages
        logger.info(
            f"[InputGuard] Message window trimmed: removed {len(to_remove)} "
            f"(window={MESSAGE_WINDOW_SIZE})"
        )

    return updates
