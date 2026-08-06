"""
v8 LangGraph 图定义 — 双模式入口.

通过环境变量 AGENT_MODE=v8 启用新架构。
默认仍使用 v7.1 的 18 节点图。

图结构：
  input_guard → lead_router → orchestrator → END
  input_guard → END（注入拦截）
"""
from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.graph import END, START, StateGraph

from .lead_router import LeadRouter
from .migration import is_scenario_v8_enabled
from .models import ExecutionPlan, V8State
from .orchestrator import Orchestrator
from .security import run_security_check

logger = logging.getLogger(__name__)

_router = LeadRouter()
_orchestrator = Orchestrator()


async def input_guard_node(state: dict) -> dict:
    """安全层节点：注入检测 + 长度截断."""
    user_input = state.get("user_input", "")
    verdict = run_security_check(user_input)

    if not verdict.passed:
        logger.warning(f"[v8:input_guard] Blocked: {verdict.blocked_reason}")
        return {
            "user_input": "",
            "final_response": "⚠️ 检测到异常输入，已拦截。如有正常需求请重新描述。",
            "final_status": "BLOCKED",
            "processing_path": "blocked",
        }

    return {"user_input": verdict.sanitized_input}


def route_after_guard(state: dict) -> str:
    """安全层后路由：拦截 → END，通过 → lead_router."""
    if state.get("processing_path") == "blocked":
        return END
    return "lead_router"


async def lead_router_node(state: dict) -> dict:
    """Lead Router 节点：解析意图 → ExecutionPlan."""
    user_input = state.get("user_input", "")
    params = state.get("normalized_params", {})
    trace_id = state.get("trace_id", "")

    plan = await _router.resolve(user_input, params, trace_id)

    # 参数校验（clarification）
    from .security import validate_params

    clarification = validate_params(plan.intent, params)
    if clarification:
        return {
            "execution_plan": plan.model_dump(),
            "final_response": f"🤔 {clarification}",
            "final_status": "CLARIFICATION",
            "processing_path": "clarification",
        }

    return {
        "execution_plan": plan.model_dump(),
        "audit_trail": [
            {
                "node": "lead_router",
                "action": "resolve",
                "scenario": plan.scenario_id,
                "match_type": plan.match_type,
                "confidence": plan.confidence,
            }
        ],
    }


def route_after_router(state: dict) -> str:
    """路由层后路由：clarification/白名单外 → END，正常 → orchestrator."""
    if state.get("processing_path") == "clarification":
        return END
    # 场景白名单检查
    plan_data = state.get("execution_plan", {})
    scenario_id = plan_data.get("scenario_id", "")
    if not is_scenario_v8_enabled(scenario_id):
        logger.info(
            f"[v8] Scenario '{scenario_id}' not in whitelist, "
            f"marking for v7.1 fallback"
        )
        return "v7_fallback"
    return "orchestrator"


async def v7_fallback_node(state: dict) -> dict:
    """回退节点：标记需要 v7.1 处理."""
    return {
        "processing_path": "v7_fallback",
        "final_status": "V7_FALLBACK",
    }


async def orchestrator_node(state: dict) -> dict:
    """Orchestrator 节点：执行三层 Agent 循环."""
    plan_data = state.get("execution_plan", {})
    plan = ExecutionPlan.model_validate(plan_data)

    v8_state = V8State(
        user_input=state.get("user_input", ""),
        trace_id=state.get("trace_id", ""),
        session_id=state.get("session_id", ""),
        execution_plan=plan,
        normalized_params=state.get("normalized_params", {}),
    )

    result = await _orchestrator.execute(v8_state)

    return {
        "final_response": result.final_response,
        "final_status": result.final_status,
        "total_llm_calls": result.total_llm_calls,
        "audit_trail": result.audit_trail,
    }


def build_v8_graph():
    """构建 v8 图（5 节点 + 条件路由）."""
    from ..graph.state import MainGraphState

    graph = StateGraph(MainGraphState)

    graph.add_node("input_guard", input_guard_node)
    graph.add_node("lead_router", lead_router_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("v7_fallback", v7_fallback_node)

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges("input_guard", route_after_guard)
    graph.add_conditional_edges("lead_router", route_after_router)
    graph.add_edge("orchestrator", END)
    graph.add_edge("v7_fallback", END)

    return graph.compile()


def is_v8_mode() -> bool:
    """检查是否启用 v8 模式."""
    return os.environ.get("AGENT_MODE", "").lower() == "v8"
