"""
条件边路由函数集 —— v7.1-Final 版本。

【功能说明】
定义主编排图中所有条件边的路由逻辑，决定节点间的跳转关系。

【路由函数清单】
- route_after_rule_engine: 规则引擎三路分发（fast_path/rule_hit/rule_miss）
- route_after_param_gate: 参数门禁路由（clarification/params_ok）
- route_by_intent: 意图路由（分发到各子图）
- route_after_analysis: 分析专家四路分发（四重终止保障）
- route_after_narrator_validation: 叙述校验路由（pass/fail）
- route_after_evaluation: 报告评估反思路由（pass/refine）

【面试知识点】
  Q: 为什么路由逻辑单独放在一个文件？
  A: 路由是图的“决策层”，与节点逻辑分离后便于独立测试和理解。
     每个路由函数都是纯函数（只读状态，无副作用），易于单元测试。
"""

from __future__ import annotations

import hashlib
import logging

from .state import MainGraphState

logger = logging.getLogger(__name__)


# =============================================================================
# 规则引擎路由
# =============================================================================


def route_after_rule_engine(state: MainGraphState) -> str:
    """规则引擎评估后的三路路由。

    【返回值】
        "fast_path" — 规则命中 + 单条查询 → 直接执行（< 1s）
        "rule_hit_complex" — 规则命中 + 复杂处理 → 参数门禁 → 正常流程
        "rule_miss" — 规则未命中 → LLM 意图分类（14b）
    """
    match = state.get("rule_match")
    if match is None:
        return "rule_miss"
    if match.get("fast_path_eligible", False):
        return "fast_path"
    return "rule_hit_complex"


# =============================================================================
# 参数门禁路由
# =============================================================================


def route_after_param_gate(state: MainGraphState) -> str:
    """参数验证后的路由。

    【返回值】
        "need_clarification" — 存在解析失败 → 向用户追问
        "params_ok" — 参数全部合法 → 进入意图路由
    """
    params = state.get("normalized_params")
    if params and params.get("parse_failures"):
        return "need_clarification"
    return "params_ok"


# =============================================================================
# 意图路由
# =============================================================================


def route_by_intent(state: MainGraphState) -> str:
    """根据识别的意图路由到对应子图。

    【路由映射】
        data_query 组 → data_collector（数据收集子图）
        batch         → batch_dispatcher（批量派发器）
        knowledge     → knowledge_qa（知识问答子图）
        report        → report_generator（报告生成）
        chitchat      → result_aggregator（直接输出）
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
        pass  # 兜底

    # 兜底：硬编码路由（渐进迁移期保留）
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

    # 默认：chitchat / unknown
    return "chitchat"


# =============================================================================
# 受控循环：四重终止保障【核心】
# 【面试知识点】这是 ReAct 模式的安全阀，防止无限循环
# =============================================================================


def route_after_analysis(state: MainGraphState) -> str:
    """ReAct 循环核心路由 —— 四重终止保障。

    【终止条件】（任一触发即退出循环）
    ① 轮次上限：loop_count >= max_loops（默认 3）
    ② LLM 预算：llm_call_count >= max_llm_calls（默认 10）
    ③ 无进展：no_progress_count >= 2
    ④ 工具全失败：所有 API 调用返回错误

    【返回值】
        "need_more_data" — 继续循环，回到数据收集
        "generate_report" — 退出循环，生成报告
        "direct_narrate" — 退出循环，直接叙述
        "degraded" — 降级模式，不允许循环
    """
    verdict = state.get("analysis_verdict")
    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)
    llm_calls = state.get("llm_call_count", 0)
    max_llm_calls = state.get("max_llm_calls", 10)
    no_progress = state.get("no_progress_count", 0)
    degradation = state.get("degradation_level", 0)

    # 熔断器：降级模式下禁止循环
    if degradation >= 2:
        logger.warning(f"[Routing] Degradation level {degradation}, forcing degraded path")
        return "degraded"

    # ① 轮次上限
    if loop_count >= max_loops:
        logger.info(f"[Routing] Loop limit reached ({loop_count}/{max_loops})")
        return _exit_loop(state, verdict)

    # ② LLM 调用预算
    if llm_calls >= max_llm_calls:
        logger.info(f"[Routing] LLM budget exhausted ({llm_calls}/{max_llm_calls})")
        return _exit_loop(state, verdict)

    # ③ 无进展检测
    if no_progress >= 2:
        logger.info(f"[Routing] No progress detected ({no_progress} consecutive)")
        return _exit_loop(state, verdict)

    # ④ 工具全失败（从 data_summary 判断）
    data_summary = state.get("collected_data_summary", "")
    if data_summary:
        lines = [line for line in data_summary.split("\n") if line.strip()]
        if lines and all("错误" in line or "error" in line.lower() for line in lines):
            logger.warning("[Routing] All tool calls failed, entering degradation")
            return "degraded"

    # LLM 判断：是否需要更多数据？
    if verdict and verdict.get("need_more_data") and verdict.get("additional_query"):
        return "need_more_data"

    return _exit_loop(state, verdict)


def _exit_loop(state: MainGraphState, verdict: dict | None) -> str:
    """确定循环退出后的路径。

    【决策逻辑】
    简单查询 → 直接叙述（7b 模型）
    复杂分析 → 报告生成（14b 模型）
    """
    intent = state.get("intent", "")

    # 简单查询意图 → 直接叙述
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

    # 根据严重程度决定是否生成报告
    if verdict and verdict.get("severity") in ("WARNING", "CRITICAL"):
        return "generate_report"

    # 默认：简单查询直接叙述，复杂查询生成报告
    if intent in ("trend_analysis", "health_check", "color_diagnosis", "spanloss_analysis"):
        return "generate_report"

    return "direct_narrate"


# =============================================================================
# 叙述校验路由 [v7.1]
# =============================================================================


def route_after_narrator_validation(state: MainGraphState) -> str:
    """[v7.1] 叙述员输出校验路由。

    【返回值】
        "pass" — 校验通过 → result_aggregator
        "fail" — 校验失败 → template_fallback（零 LLM）
    """
    if state.get("narrator_validation_passed", True):
        return "pass"
    logger.info("[Routing] Narrator validation failed, using template fallback")
    return "fail"


# =============================================================================
# 报告评估（反思循环）路由
# =============================================================================


def route_after_evaluation(state: MainGraphState) -> str:
    """反思循环路由 —— 最多 1 次优化。

    【返回值】
        "pass" — 报告质量可接受 → result_aggregator
        "refine" — 需要改进 → report_generator（最多 1 次）
    """
    eval_result = state.get("report_eval", {})
    refinement_count = eval_result.get("refinement_count", 0)

    if eval_result.get("passed", True):
        return "pass"

    # 1 次优化后强制通过
    if refinement_count >= 1:
        logger.info("[Routing] Report refinement limit reached, forcing pass")
        return "pass"

    return "refine"


# =============================================================================
# 工具函数
# =============================================================================


def compute_action_signature(action: str, observation: str) -> str:
    """计算动作 + 观察的 MD5 哈希，用于无进展检测。

    【功能说明】
    分析专家用此函数检测循环是否取得进展：
    相同动作 + 相同观察 = 没有新信息 = 无进展。
    """
    content = f"{action}|{observation[:500]}"  # 截断为 500 字符
    return hashlib.md5(content.encode()).hexdigest()
