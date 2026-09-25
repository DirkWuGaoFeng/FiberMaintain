"""
Orchestrator — 三层 Agent 循环控制器.

职责：
1. 接收 ExecutionPlan
2. 分派 Collection → Analysis（循环 ≤ N 轮）
3. Analysis 完成后分派 Expression
4. 返回最终结果

循环终止条件：
- Analysis 判定完成（needs_more_data=False）
- 达到 max_loop_rounds
- 无进展检测（数据签名不变）
- [P0] Agent 级熔断器触发（死循环/LLM 预算耗尽）
"""

from __future__ import annotations

import hashlib
import logging

from ..resilience.agent_circuit_breaker import get_agent_circuit_breaker
from .agents.analysis_agent import AnalysisAgent
from .agents.collection_agent import CollectionAgent
from .agents.expression_agent import ExpressionAgent
from .models import LoopContext, V8State

logger = logging.getLogger(__name__)


class Orchestrator:
    """三层 Agent 循环控制器."""

    def __init__(self):
        self.collection_agent = CollectionAgent()
        self.analysis_agent = AnalysisAgent()
        self.expression_agent = ExpressionAgent()

    async def execute(self, state: V8State) -> V8State:
        """
        执行完整的三层 Agent 流程.

        Collection ↔ Analysis 循环 → Expression → 最终输出
        """
        plan = state.execution_plan
        if not plan:
            state.final_response = "❌ 无法生成执行计划"
            state.final_status = "ERROR"
            return state

        trace_id = state.trace_id
        loop_ctx = LoopContext(max_rounds=plan.max_loop_rounds)
        last_signature = ""

        # [P0] 初始化 Agent 级熔断器
        circuit_breaker = get_agent_circuit_breaker(
            max_analysis_loops=3,
            max_no_progress_loops=3,
            max_llm_budget=plan.max_loop_rounds * 4,
        )
        circuit_breaker.reset()
        circuit_breaker.set_start_time()

        # ===== 采集 ↔ 分析循环 =====
        while loop_ctx.round < loop_ctx.max_rounds:
            loop_ctx.round += 1
            logger.info(f"[TRACE:{trace_id}] [Orchestrator] Loop round " f"{loop_ctx.round}/{loop_ctx.max_rounds}")

            # --- 采集 ---
            collection_context = {
                "trace_id": trace_id,
                "user_input": state.user_input,
                "normalized_params": state.normalized_params,
                "loop_round": loop_ctx.round,
            }
            # 如果是补充采集，传入 additional_query
            if loop_ctx.analysis_verdicts:
                last_verdict = loop_ctx.analysis_verdicts[-1]
                if last_verdict.get("additional_query"):
                    collection_context["additional_query"] = last_verdict["additional_query"]

            collection_result = await self.collection_agent.run(plan, collection_context)
            state.collection_result = collection_result
            state.total_llm_calls += collection_result.llm_calls

            if not collection_result.success:
                logger.warning(f"[TRACE:{trace_id}] [Orchestrator] Collection failed")
                loop_ctx.terminated_reason = "collection_error"
                break

            # 无进展检测
            raw_data = collection_result.data.get("raw_summary", "")
            signature = hashlib.md5(raw_data.encode()).hexdigest()

            # [P0] 熔断器：记录数据签名变化
            if last_signature:
                # 只在 Analysis 阶段后记录（通过 needs_more_data 判断）
                pass

            if signature == last_signature and loop_ctx.round > 1:
                logger.info(f"[TRACE:{trace_id}] [Orchestrator] No progress, terminating")
                loop_ctx.terminated_reason = "no_progress"
                break
            last_signature = signature
            loop_ctx.collection_results.append(collection_result.data)

            # --- 分析 ---
            analysis_context = {
                "trace_id": trace_id,
                "user_input": state.user_input,
                "collection_data": collection_result.data,
                "normalized_params": state.normalized_params,
                "conversation_summary": getattr(state, "conversation_summary", {}),
            }
            analysis_result = await self.analysis_agent.run(plan, analysis_context)
            state.analysis_result = analysis_result
            state.total_llm_calls += analysis_result.llm_calls

            if not analysis_result.success:
                loop_ctx.terminated_reason = "analysis_error"
                break

            verdict = analysis_result.data.get("verdict", {})
            loop_ctx.analysis_verdicts.append(verdict)

            # 检查是否需要追加采集
            if not analysis_result.needs_more_data:
                loop_ctx.terminated_reason = "complete"
                break

            # [P0] Agent 级熔断器：记录分析结果并检查
            circuit_breaker.record_analysis_result(
                needs_more_data=analysis_result.needs_more_data,
                data_signature=signature,
            )
            if analysis_result.llm_calls > 0:
                for _ in range(analysis_result.llm_calls):
                    circuit_breaker.record_llm_call()

            cb_verdict = circuit_breaker.check()
            if cb_verdict.should_terminate:
                logger.warning(f"[TRACE:{trace_id}] [Orchestrator] " f"Circuit breaker: {cb_verdict.reason}")
                loop_ctx.terminated_reason = cb_verdict.reason
                break

        # 循环自然结束（达到 max_rounds）
        if not loop_ctx.terminated_reason:
            loop_ctx.terminated_reason = "max_rounds"

        # ===== 表达 =====
        analysis_data = {}
        if state.analysis_result and state.analysis_result.success:
            analysis_data = state.analysis_result.data
        elif loop_ctx.analysis_verdicts:
            analysis_data = {"verdict": loop_ctx.analysis_verdicts[-1]}

        expression_context = {
            "trace_id": trace_id,
            "analysis_data": analysis_data,
            "user_id": getattr(state, "user_id", ""),
        }
        expression_result = await self.expression_agent.run(plan, expression_context)
        state.expression_result = expression_result

        # ===== 最终输出 =====
        if expression_result.success:
            state.final_response = expression_result.data.get("response", "")
            verdict = analysis_data.get("verdict", {})
            state.final_status = verdict.get("status", "UNKNOWN")
        else:
            state.final_response = f"❌ 输出格式化失败: {expression_result.error}"
            state.final_status = "ERROR"

        # 审计
        state.loop_context = loop_ctx
        state.audit_trail.append(
            {
                "node": "orchestrator",
                "loop_rounds": loop_ctx.round,
                "terminated_reason": loop_ctx.terminated_reason,
                "total_llm_calls": state.total_llm_calls,
                "circuit_breaker": {
                    "triggered": circuit_breaker.check().should_terminate,
                    "reason": circuit_breaker.check().reason,
                    "loop_count": circuit_breaker.loop_count,
                    "llm_calls": circuit_breaker.llm_calls,
                },
            }
        )

        logger.info(
            f"[TRACE:{trace_id}] [Orchestrator] DONE "
            f"rounds={loop_ctx.round} reason={loop_ctx.terminated_reason} "
            f"status={state.final_status}"
        )
        return state
