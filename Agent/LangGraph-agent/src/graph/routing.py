"""
Conditional edge routing functions for the main graph — v7.1-Final.

Implements:
- Rule engine three-way routing (fast_path / rule_hit / rule_miss)
- Parameter gate routing (clarification / params_ok)
- Intent-based routing to sub-graphs
- Four termination safeguards for Controlled Loop
- Narrator validation routing [v7.1]
- Report evaluation Reflection routing
"""

from __future__ import annotations

import hashlib
import logging

from .state import MainGraphState

logger = logging.getLogger(__name__)


# =============================================================================
# Rule Engine Routing
# =============================================================================


def route_after_rule_engine(state: MainGraphState) -> str:
    """
    Three-way routing after rule engine evaluation.

    Returns:
        "fast_path" — Rule hit + single query → direct execution (< 1s)
        "rule_hit_complex" — Rule hit + complex → param_gate → normal flow
        "rule_miss" — No rule match → LLM intent classification (14b)
    """
    match = state.get("rule_match")
    if match is None:
        return "rule_miss"
    if match.get("fast_path_eligible", False):
        return "fast_path"
    return "rule_hit_complex"


# =============================================================================
# Parameter Gate Routing
# =============================================================================


def route_after_param_gate(state: MainGraphState) -> str:
    """
    Routing after parameter validation.

    Returns:
        "need_clarification" — Parse failures exist → interrupt() for user input
        "params_ok" — All parameters valid → proceed to intent routing
    """
    params = state.get("normalized_params")
    if params and params.get("parse_failures"):
        return "need_clarification"
    return "params_ok"


# =============================================================================
# Intent-Based Routing
# =============================================================================


def route_by_intent(state: MainGraphState) -> str:
    """
    Route to appropriate sub-graph based on identified intent.

    Reads from RoutingRegistry (Skill system) with hardcoded fallback.

    Mapping:
        data_query group → data_collector
        batch → batch_dispatcher
        knowledge → knowledge_qa
        report → report_generator
        chitchat → result_aggregator
    """
    intent = state.get("intent", "chitchat")

    # Skill group → 图条件边路由名（与 main_graph 边映射一致）
    group_to_route = {
        "data_query": "data_query",
        "batch": "batch_query",
        "knowledge": "knowledge_qa",
        "report": "report",
        "chitchat": "chitchat",
    }

    # 优先从 Skill 系统路由
    try:
        from ..skills.loader import get_registries

        group = get_registries()["routing"].resolve(intent)
        if group != "chitchat" or intent == "chitchat":
            return group_to_route.get(group, group)
    except (ImportError, KeyError):
        pass  # Fallback

    # Fallback: 硬编码路由（渐进迁移期保留）
    data_intents = (
        "single_query",
        "spanloss_analysis",
        "color_diagnosis",
        "trend_analysis",
        "health_check",
        "spanloss_query",
        "connection_query",
        "performance_query",
        "fiber_alarm_query",
        "port_alarm_query",
        "colored_query",
        "stats_query",
        "trend_query",
    )
    if intent in data_intents:
        return "data_query"

    if intent == "batch_query":
        return "batch_query"

    if intent == "knowledge_qa":
        return "knowledge_qa"

    if intent == "report_generation":
        return "report"

    # Default: chitchat / unknown
    return "chitchat"


# =============================================================================
# Controlled Loop: Four Termination Safeguards [Core]
# =============================================================================


def route_after_analysis(state: MainGraphState) -> str:
    """
    ReAct Loop core routing — Four Termination Safeguards.

    Termination conditions (any one triggers loop exit):
    ① Round limit: loop_count >= max_loops (3)
    ② LLM budget: llm_call_count >= max_llm_calls (10)
    ③ No progress: no_progress_count >= 2
    ④ Tool all-fail: all API calls returned errors

    Returns:
        "need_more_data" — Continue loop, go back to data_collector
        "generate_report" — Exit loop, generate report
        "direct_narrate" — Exit loop, direct narration
        "degraded" — Degradation mode, no loop allowed
    """
    verdict = state.get("analysis_verdict")
    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)
    llm_calls = state.get("llm_call_count", 0)
    max_llm_calls = state.get("max_llm_calls", 10)
    no_progress = state.get("no_progress_count", 0)
    degradation = state.get("degradation_level", 0)

    # Circuit breaker: degradation mode disallows Loop
    if degradation >= 2:
        logger.warning(f"[Routing] Degradation level {degradation}, forcing degraded path")
        return "degraded"

    # ① Round limit
    if loop_count >= max_loops:
        logger.info(f"[Routing] Loop limit reached ({loop_count}/{max_loops})")
        return _exit_loop(state, verdict)

    # ② LLM call budget
    if llm_calls >= max_llm_calls:
        logger.info(f"[Routing] LLM budget exhausted ({llm_calls}/{max_llm_calls})")
        return _exit_loop(state, verdict)

    # ③ No progress detection
    if no_progress >= 2:
        logger.info(f"[Routing] No progress detected ({no_progress} consecutive)")
        return _exit_loop(state, verdict)

    # ④ Tool all-fail (from data_summary)
    data_summary = state.get("collected_data_summary", "")
    if data_summary:
        lines = [line for line in data_summary.split("\n") if line.strip()]
        if lines and all("错误" in line or "error" in line.lower() for line in lines):
            logger.warning("[Routing] All tool calls failed, entering degradation")
            return "degraded"

    # LLM verdict: does it need more data?
    if verdict and verdict.get("need_more_data") and verdict.get("additional_query"):
        return "need_more_data"

    return _exit_loop(state, verdict)


def _exit_loop(state: MainGraphState, verdict: dict | None) -> str:
    """
    Determine exit path after loop termination.

    Simple queries → direct narration (7b)
    Complex analysis → report generation (14b)
    """
    intent = state.get("intent", "")

    # Simple query intents → direct narrate
    simple_intents = (
        "spanloss_query",
        "connection_query",
        "performance_query",
        "fiber_alarm_query",
        "port_alarm_query",
        "colored_query",
        "stats_query",
        "single_query",
    )
    if intent in simple_intents:
        return "direct_narrate"

    # Check severity for report decision
    if verdict and verdict.get("severity") in ("WARNING", "CRITICAL"):
        return "generate_report"

    # Default: direct narration for simple, report for complex
    if intent in ("trend_analysis", "health_check", "color_diagnosis", "spanloss_analysis"):
        return "generate_report"

    return "direct_narrate"


# =============================================================================
# Narrator Validation Routing [v7.1]
# =============================================================================


def route_after_narrator_validation(state: MainGraphState) -> str:
    """
    [v7.1] Narrator output validation routing.

    Returns:
        "pass" — Validation passed → result_aggregator
        "fail" — Validation failed → template_fallback (zero LLM)
    """
    if state.get("narrator_validation_passed", True):
        return "pass"
    logger.info("[Routing] Narrator validation failed, using template fallback")
    return "fail"


# =============================================================================
# Report Evaluation (Reflection) Routing
# =============================================================================


def route_after_evaluation(state: MainGraphState) -> str:
    """
    Reflection Loop routing — at most 1 refinement.

    Returns:
        "pass" — Report quality acceptable → result_aggregator
        "refine" — Needs improvement → report_generator (max 1 time)
    """
    eval_result = state.get("report_eval", {})
    refinement_count = eval_result.get("refinement_count", 0)

    if eval_result.get("passed", True):
        return "pass"

    # Force pass after 1 refinement attempt
    if refinement_count >= 1:
        logger.info("[Routing] Report refinement limit reached, forcing pass")
        return "pass"

    return "refine"


# =============================================================================
# Utility Functions
# =============================================================================


def compute_action_signature(action: str, observation: str) -> str:
    """
    Compute MD5 hash of action + observation for no-progress detection.

    Used by analysis_expert to detect when the loop is making no progress
    (same action + same observation = no new information gained).
    """
    content = f"{action}|{observation[:500]}"  # Truncate to 500 chars
    return hashlib.md5(content.encode()).hexdigest()
