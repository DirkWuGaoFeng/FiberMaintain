"""
Main orchestration graph — v7.1-Final.

Architecture: Harness + Controlled Loop + Narrator Validation Loop.

18 nodes:
  input_guard → rule_engine → [fast_path_executor | param_gate | intent_classifier]
  → intent_router → [data_collector | batch_dispatcher | knowledge_qa | result_aggregator]
  → rule_judgment → analysis_expert → [loop back | narrator | report_generator | degradation]
  → narrator → narrator_validator → [result_aggregator | template_fallback]
  → report_generator → report_evaluator → [result_aggregator | refine loop]
  → result_aggregator → END

Four termination safeguards:
  ① Round limit (≤3)  ② LLM budget (≤10)
  ③ No-progress detection  ④ Tool all-fail circuit breaker
"""

from __future__ import annotations

import logging
import os

from langgraph.graph import END, START, StateGraph

from ..config import CHECKPOINT_DB
from .routing import (
    route_after_analysis,
    route_after_evaluation,
    route_after_narrator_validation,
    route_after_param_gate,
    route_after_rule_engine,
    route_by_intent,
)
from .state import MainGraphState

logger = logging.getLogger(__name__)


def build_main_graph():
    """
    Build the main orchestration graph (v7.1-Final).

    Returns:
        Compiled StateGraph with SQLite checkpointer.
    """
    # v8 模式切换
    from ..v8.graph import build_v8_graph, is_v8_mode

    if is_v8_mode():
        logger.info("[MainGraph] AGENT_MODE=v8, using v8 three-layer architecture")
        return build_v8_graph()

    # Lazy imports to avoid circular dependencies
    from ..nodes.input_guard import input_guard_node
    from ..nodes.rule_engine import rule_engine_node
    from ..nodes.fast_path_executor import fast_path_executor_node
    from ..nodes.intent_classifier import intent_classifier_node
    from ..nodes.param_gate import param_gate_node
    from ..nodes.clarification import clarification_node
    from ..nodes.intent_router import intent_router_node
    from ..nodes.rule_judgment import rule_judgment_node
    from ..nodes.analysis_expert import analysis_expert_node
    from ..nodes.narrator import narrator_node
    from ..nodes.narrator_validator import narrator_validator_node
    from ..nodes.template_fallback import template_fallback_node
    from ..nodes.report_generator import report_generator_node
    from ..nodes.report_evaluator import report_evaluator_node
    from ..nodes.result_aggregator import result_aggregator_node
    from ..nodes.degradation_handler import degradation_handler_node
    from ..nodes.batch_dispatcher import batch_dispatcher_node
    from ..graph.subgraphs.data_collector import data_collector_subgraph
    from ..graph.subgraphs.knowledge_assistant import knowledge_assistant_subgraph

    graph = StateGraph(MainGraphState)

    # ===== Node Registration (18 nodes) =====
    graph.add_node("input_guard", input_guard_node)
    graph.add_node("rule_engine", rule_engine_node)
    graph.add_node("fast_path_executor", fast_path_executor_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("param_gate", param_gate_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("data_collector", data_collector_subgraph)
    graph.add_node("rule_judgment", rule_judgment_node)
    graph.add_node("analysis_expert", analysis_expert_node)
    graph.add_node("narrator", narrator_node)
    graph.add_node("narrator_validator", narrator_validator_node)
    graph.add_node("template_fallback", template_fallback_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("report_evaluator", report_evaluator_node)
    graph.add_node("batch_dispatcher", batch_dispatcher_node)
    graph.add_node("knowledge_qa", knowledge_assistant_subgraph)
    graph.add_node("result_aggregator", result_aggregator_node)
    graph.add_node("degradation_handler", degradation_handler_node)

    # ===== Edge Definitions =====

    # Entry: input_guard → rule_engine
    graph.add_edge(START, "input_guard")
    graph.add_edge("input_guard", "rule_engine")

    # Rule engine → three-way routing
    graph.add_conditional_edges(
        "rule_engine",
        route_after_rule_engine,
        {
            "fast_path": "fast_path_executor",
            "rule_hit_complex": "param_gate",
            "rule_miss": "intent_classifier",
        },
    )

    # Fast Path → direct to result
    graph.add_edge("fast_path_executor", "result_aggregator")

    # LLM intent classification → param gate
    graph.add_edge("intent_classifier", "param_gate")

    # Param gate → clarification or intent routing
    graph.add_conditional_edges(
        "param_gate",
        route_after_param_gate,
        {
            "need_clarification": "clarification",
            "params_ok": "intent_router",
        },
    )

    # Clarification loops back to rule_engine (via Command/interrupt)
    graph.add_edge("clarification", "rule_engine")

    # Intent router → sub-graphs
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "data_query": "data_collector",
            "batch_query": "batch_dispatcher",
            "knowledge_qa": "knowledge_qa",
            "report": "data_collector",
            "chitchat": "result_aggregator",
        },
    )

    # ===== Core: Controlled Loop =====
    graph.add_edge("data_collector", "rule_judgment")
    graph.add_edge("rule_judgment", "analysis_expert")

    # Analysis → four-way routing (Loop core)
    graph.add_conditional_edges(
        "analysis_expert",
        route_after_analysis,
        {
            "need_more_data": "data_collector",  # ReAct loop back
            "generate_report": "report_generator",
            "direct_narrate": "narrator",
            "degraded": "degradation_handler",
        },
    )

    # ===== Narrator → Validator → Validation Loop [v7.1] =====
    graph.add_edge("narrator", "narrator_validator")
    graph.add_conditional_edges(
        "narrator_validator",
        route_after_narrator_validation,
        {
            "pass": "result_aggregator",
            "fail": "template_fallback",
        },
    )
    graph.add_edge("template_fallback", "result_aggregator")

    # ===== Reflection Loop (Report) =====
    graph.add_edge("report_generator", "report_evaluator")
    graph.add_conditional_edges(
        "report_evaluator",
        route_after_evaluation,
        {
            "pass": "result_aggregator",
            "refine": "report_generator",  # ≤1 refinement
        },
    )

    # Batch / Knowledge / Degradation → result
    graph.add_edge("batch_dispatcher", "result_aggregator")
    graph.add_edge("knowledge_qa", "result_aggregator")
    graph.add_edge("degradation_handler", "result_aggregator")

    # Result → END
    graph.add_edge("result_aggregator", END)

    # ===== Compile with Checkpointer =====
    checkpointer = _create_checkpointer()

    return graph.compile(checkpointer=checkpointer)


def _create_checkpointer():
    """Create checkpointer for state persistence.

    [P0-B] SqliteSaver persists thread state across process restarts
    (multi-turn follow-ups are a real usage pattern). Falls back to
    MemorySaver when the sqlite checkpoint package is unavailable.
    """
    import sqlite3

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        logger.info(f"[Graph] Using SqliteSaver checkpointer ({CHECKPOINT_DB})")
        return SqliteSaver(conn)
    except ImportError:
        logger.warning("[Graph] langgraph-checkpoint-sqlite missing, falling back to MemorySaver")
    except Exception as e:
        logger.warning(f"[Graph] SqliteSaver init failed ({e}), falling back to MemorySaver")

    try:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    except ImportError:
        logger.warning("[Graph] No checkpointer available")
        return None


# =============================================================================
# Module-level graph instance (lazy initialization)
# =============================================================================

_graph_instance = None


def get_graph():
    """Get or create the main graph instance (singleton)."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_main_graph()
    return _graph_instance
