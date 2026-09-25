"""
意图路由器节点 — 纯路由，不进行处理。

根据验证后的意图路由到相应的子图。
这是一个直通节点，仅用于保持图结构清晰。
"""

from __future__ import annotations

import logging

from ..context.task_context import _derive_task_plan
from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def intent_router_node(state: MainGraphState) -> dict:
    """
    意图路由器：用于条件边路由的直通节点。

    实际的路由逻辑位于 routing.py::route_by_intent()。
    本节点仅记录路由决策日志，用于审计目的。
    同时写入任务计划（书籍 Ch2：任务上下文显式化）。
    """
    intent = state.get("intent", "chitchat")
    logger.info(f"[IntentRouter] Routing intent: {intent}")

    return {
        "audit_trail": [{"event": "intent_routed", "intent": intent}],
        # 任务计划在意图确认后写入 state，供后续节点注入 prompt
        "task_plan": _derive_task_plan(state),
    }
