"""
Main orchestration graph: StateGraph with 11 nodes and conditional edges.

This is the entry point for the Fiber Maintenance Agent.
"""

from __future__ import annotations

import logging
import os

from langgraph.graph import END, START, StateGraph

from ..nodes import (
    batch_aggregator_node,
    batch_dispatcher_node,
    batch_worker_node,
    degradation_handler_node,
    intent_classifier_node,
    result_aggregator_node,
    task_decomposer_node,
)
from .routing import check_degradation, route_by_intent, route_after_analysis
from .state import FiberAgentState
from .subgraphs.analysis_expert import analysis_expert_subgraph
from .subgraphs.data_collector import data_collector_subgraph
from .subgraphs.knowledge_assistant import knowledge_assistant_subgraph
from .subgraphs.report_generator import report_generator_subgraph

logger = logging.getLogger(__name__)


def build_main_graph():
    """
    Build the main orchestration graph.

    Architecture:
      START -> intent_classifier -> task_decomposer
        -> (conditional edge: intent routing)
          -> data_collector / batch_dispatcher / report_generator / knowledge_assistant / result_aggregator
        -> result_aggregator -> degradation_handler -> END

    Checkpointer: AsyncSqliteSaver for state persistence (checkpoint resume)
    """
    graph = StateGraph(FiberAgentState)

    # ===== Register Nodes =====
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("task_decomposer", task_decomposer_node)
    graph.add_node("data_collector", data_collector_subgraph)
    graph.add_node("analysis_expert", analysis_expert_subgraph)
    graph.add_node("report_generator", report_generator_subgraph)
    graph.add_node("knowledge_assistant", knowledge_assistant_subgraph)
    graph.add_node("batch_dispatcher", batch_dispatcher_node)
    graph.add_node("batch_worker", batch_worker_node)
    graph.add_node("batch_aggregator", batch_aggregator_node)
    graph.add_node("result_aggregator", result_aggregator_node)
    graph.add_node("degradation_handler", degradation_handler_node)

    # ===== Fixed Edges =====
    graph.add_edge(START, "intent_classifier")
    graph.add_edge("intent_classifier", "task_decomposer")

    # ===== Conditional Edge: Intent Routing =====
    graph.add_conditional_edges(
        "task_decomposer",
        route_by_intent,
        {
            "single_query": "data_collector",
            "batch_query": "batch_dispatcher",
            "spanloss_analysis": "data_collector",
            "color_diagnosis": "data_collector",
            "trend_analysis": "data_collector",
            "health_check": "data_collector",
            "report_generation": "report_generator",
            "knowledge_qa": "knowledge_assistant",
            "chitchat": "result_aggregator",
        },
    )

    # ===== Data Collection Pipeline =====
    graph.add_edge("data_collector", "analysis_expert")
    graph.add_conditional_edges(
        "analysis_expert",
        route_after_analysis,
        {
            "need_report": "report_generator",
            "direct_answer": "result_aggregator",
        },
    )
    graph.add_edge("report_generator", "result_aggregator")
    graph.add_edge("knowledge_assistant", "result_aggregator")

    # ===== Batch Pipeline (Send Map-Reduce) =====
    # batch_dispatcher returns list[Send] -> LangGraph dispatches to batch_worker
    graph.add_edge("batch_worker", "batch_aggregator")
    graph.add_edge("batch_aggregator", "analysis_expert")

    # ===== Result Pipeline =====
    graph.add_edge("result_aggregator", "degradation_handler")
    graph.add_conditional_edges(
        "degradation_handler",
        check_degradation,
        {
            "normal": END,
            "fallback": "degradation_handler",  # Loop retry
        },
    )

    # ===== Compile with Checkpointer =====
    checkpointer = _create_checkpointer()

    return graph.compile(
        checkpointer=checkpointer,
    )


def _create_checkpointer():
    """Create the appropriate checkpointer based on environment."""
    db_path = os.environ.get("CHECKPOINT_DB", "data/checkpoints.db")

    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        return AsyncSqliteSaver.from_conn_string(db_path)
    except ImportError:
        logger.warning("AsyncSqliteSaver not available, using in-memory checkpointer")
        try:
            from langgraph.checkpoint.memory import MemorySaver
            return MemorySaver()
        except ImportError:
            logger.warning("MemorySaver not available, no checkpointer")
            return None


# Module-level graph instance (for LangGraph Studio / LangServe)
# Lazy initialization to avoid import-time side effects
_graph_instance = None


def get_graph():
    """Get or create the main graph instance."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_main_graph()
    return _graph_instance
