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
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from .agents.analysis_agent import AnalysisAgent
from .agents.collection_agent import CollectionAgent
from .agents.expression_agent import ExpressionAgent
from .models import AgentResult, ExecutionPlan, LoopContext, V8State

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

        # ===== Collection ↔ Analysis Loop =====
        while loop_ctx.round < loop_ctx.max_rounds:
            loop_ctx.round += 1
            logger.info(
                f"[TRACE:{trace_id}] [Orchestrator] Loop round "
                f"{loop_ctx.round}/{loop_ctx.max_rounds}"
            )

            # --- Collection ---
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
                    collection_context["additional_query"] = last_verdict[
                        "additional_query"
                    ]

            collection_result = await self.collection_agent.run(
                plan, collection_context
            )
            state.collection_result = collection_result
            state.total_llm_calls += collection_result.llm_calls

            if not collection_result.success:
                logger.warning(f"[TRACE:{trace_id}] [Orchestrator] Collection failed")
                loop_ctx.terminated_reason = "collection_error"
                break

            # 无进展检测
            raw_data = collection_result.data.get("raw_summary", "")
            signature = hashlib.md5(raw_data.encode()).hexdigest()
            if signature == last_signature and loop_ctx.round > 1:
                logger.info(
                    f"[TRACE:{trace_id}] [Orchestrator] No progress, terminating"
                )
                loop_ctx.terminated_reason = "no_progress"
                break
            last_signature = signature
            loop_ctx.collection_results.append(collection_result.data)

            # --- Analysis ---
            analysis_context = {
                "trace_id": trace_id,
                "user_input": state.user_input,
                "collection_data": collection_result.data,
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

        # 循环自然结束（达到 max_rounds）
        if not loop_ctx.terminated_reason:
            loop_ctx.terminated_reason = "max_rounds"

        # ===== Expression =====
        analysis_data = {}
        if state.analysis_result and state.analysis_result.success:
            analysis_data = state.analysis_result.data
        elif loop_ctx.analysis_verdicts:
            analysis_data = {"verdict": loop_ctx.analysis_verdicts[-1]}

        expression_context = {
            "trace_id": trace_id,
            "analysis_data": analysis_data,
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
            }
        )

        logger.info(
            f"[TRACE:{trace_id}] [Orchestrator] DONE "
            f"rounds={loop_ctx.round} reason={loop_ctx.terminated_reason} "
            f"status={state.final_status}"
        )
        return state
