"""
Intent Router Node — Pure routing, no processing.

Routes to appropriate sub-graph based on validated intent.
This is a pass-through node that exists solely for graph structure clarity.
"""

from __future__ import annotations

import logging

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def intent_router_node(state: MainGraphState) -> dict:
    """
    Intent router: pass-through node for conditional edge routing.

    The actual routing logic is in routing.py::route_by_intent().
    This node simply logs the routing decision for audit purposes.
    """
    intent = state.get("intent", "chitchat")
    logger.info(f"[IntentRouter] Routing intent: {intent}")

    return {
        "audit_trail": [{"event": "intent_routed", "intent": intent}],
    }
