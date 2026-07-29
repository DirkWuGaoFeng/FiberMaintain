"""
Conditional edge routing functions for the main graph.

Implements intent-based routing and degradation checks.
"""

from __future__ import annotations

import logging

from .state import FiberAgentState

logger = logging.getLogger(__name__)


def route_by_intent(state: FiberAgentState) -> str:
    """
    Conditional edge: route to appropriate sub-graph based on intent.

    Mapping:
      single_query      -> data_collector
      batch_query       -> batch_dispatcher
      spanloss_analysis -> data_collector (then analysis)
      color_diagnosis   -> data_collector (then analysis)
      trend_analysis    -> data_collector (then analysis)
      health_check      -> data_collector (then analysis)
      report_generation -> report_generator
      knowledge_qa      -> knowledge_assistant
      chitchat          -> result_aggregator
    """
    intent = state.get("intent")

    if intent is None or intent.confidence < 0.6:
        logger.warning(f"[Routing] Low confidence ({intent.confidence if intent else 'None'}), routing to chitchat")
        return "chitchat"

    # Analysis/diagnosis intents go through data_collector first
    if intent.intent in ("spanloss_analysis", "color_diagnosis",
                         "trend_analysis", "health_check"):
        return "single_query"  # Routes to data_collector -> analysis pipeline

    return intent.intent


def route_after_analysis(state: FiberAgentState) -> str:
    """
    Conditional edge: after analysis, decide whether to generate a report
    or return a direct answer.
    """
    intent = state.get("intent")

    # Report generation always goes through report sub-graph
    if intent and intent.intent == "report_generation":
        return "need_report"

    # Analysis with significant findings -> generate report
    analysis = state.get("analysis_result")
    if analysis and analysis.get("severity") in ("high", "critical"):
        return "need_report"

    return "direct_answer"


def check_degradation(state: FiberAgentState) -> str:
    """
    Conditional edge: check degradation level after result aggregation.

    Returns:
      "normal" -> END
      "fallback" -> degradation_handler (loop retry)
    """
    level = state.get("degradation_level", "L1")

    if level in ("L3", "L4"):
        # Already in degradation mode, output directly
        return "normal"

    # Check for errors that might trigger degradation
    error_log = state.get("error_log", [])
    if len(error_log) >= 3:
        logger.warning(f"[Routing] Multiple errors detected ({len(error_log)}), degrading")
        return "fallback"

    return "normal"


def dispatch_chunks(state: FiberAgentState):
    """
    Conditional edge for batch dispatch: returns Send list for parallel execution.
    This is handled by batch_dispatcher_node which returns list[Send].
    """
    # This function is a placeholder - the actual dispatching is done
    # by batch_dispatcher_node which returns Send objects directly
    pass
