"""
Task decomposer node: breaks down user request into sub-tasks.
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import FiberAgentState, TaskPlan
from ..llm.provider import get_primary_llm
from ..llm.prompts import TASK_DECOMPOSER_PROMPT

logger = logging.getLogger(__name__)


async def task_decomposer_node(state: FiberAgentState) -> dict:
    """
    Task decomposition node.
    Analyzes the intent and creates an ordered sub-task plan.
    """
    intent = state.get("intent")
    if intent is None:
        return {"task_plan": [], "current_subtask_index": 0}

    user_msg = state["messages"][-1].content if state["messages"] else ""
    logger.info(f"[TaskDecomposer] Decomposing for intent: {intent.intent}")

    # Simple rule-based decomposition for common intents
    if intent.intent == "single_query":
        subtasks = [f"Query fiber data for {fid}" for fid in intent.fiber_ids]
        if not subtasks:
            subtasks = ["Query fiber data"]
        return {"task_plan": subtasks, "current_subtask_index": 0}

    elif intent.intent == "batch_query":
        return {
            "task_plan": [f"Batch query {len(intent.fiber_ids)} fibers"],
            "current_subtask_index": 0,
        }

    elif intent.intent in ("spanloss_analysis", "color_diagnosis"):
        subtasks = [
            "Collect fiber performance data",
            "Collect fiber span loss data",
            "Analyze anomalies",
        ]
        return {"task_plan": subtasks, "current_subtask_index": 0}

    elif intent.intent == "trend_analysis":
        return {
            "task_plan": [
                "Collect historical statistics",
                "Analyze trend patterns",
                "Generate trend report",
            ],
            "current_subtask_index": 0,
        }

    elif intent.intent == "health_check":
        return {
            "task_plan": [
                "Query all fiber stats",
                "Check alarm status",
                "Generate health report",
            ],
            "current_subtask_index": 0,
        }

    elif intent.intent == "report_generation":
        return {
            "task_plan": ["Generate maintenance report"],
            "current_subtask_index": 0,
        }

    elif intent.intent == "knowledge_qa":
        return {
            "task_plan": ["Search knowledge base", "Generate answer"],
            "current_subtask_index": 0,
        }

    else:  # chitchat
        return {"task_plan": ["Respond to user"], "current_subtask_index": 0}
