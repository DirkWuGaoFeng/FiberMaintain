"""
Data collector sub-graph: ReAct Agent + ToolNode.

This is the ONLY sub-graph that binds backend API tools (P2 principle).
Uses create_react_agent for automatic tool-calling loop.
"""

from __future__ import annotations

import logging

from langgraph.prebuilt import create_react_agent

from ...llm.provider import get_data_collector_llm
from ...llm.prompts import DATA_COLLECTOR_SYSTEM_PROMPT
from ...tools import DATA_COLLECTOR_TOOLS

logger = logging.getLogger(__name__)


def build_data_collector_subgraph():
    """
    Build the data collector sub-graph.

    Architecture: ReAct Agent with ToolNode
    - LLM: qwen2.5:7b, temperature=0.0 (tool calling accuracy)
    - Tools: 12 backend API tools (topology, performance, alarm, colored, stats)
    - Recursion limit: 10 (prevent infinite tool-calling loops)
    """
    llm = get_data_collector_llm()

    agent = create_react_agent(
        model=llm,
        tools=DATA_COLLECTOR_TOOLS,
        prompt=DATA_COLLECTOR_SYSTEM_PROMPT,
        # Max tool-calling rounds (prevent infinite loops)
        recursion_limit=10,
    )

    return agent


# Module-level compiled sub-graph
data_collector_subgraph = build_data_collector_subgraph()
