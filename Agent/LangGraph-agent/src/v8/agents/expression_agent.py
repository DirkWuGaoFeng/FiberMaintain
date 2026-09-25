"""
Expression Agent — 表达输出层.

职责：
- 将 Analysis verdict 格式化为用户友好的输出
- 支持多种输出格式：narrative / table / report / raw
- report 模式：调用 7b LLM 生成自然语言分析报告
- 数字模板填充（反幻觉）
- 不调用后端工具，不修改结论
- [P0] 输出侧护栏：PII 过滤 + 结构化验证
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...governance.number_validator import validate_narration_numbers
from ..models import AgentLayer, AgentResult, ExecutionPlan
from ..output_guard import run_output_guard
from ..resilience import get_llm_breaker
from .base import BaseAgent

logger = logging.getLogger(__name__)

# 状态 emoji 映射
_STATUS_EMOJI = {
    "NORMAL": "✅",
    "WARNING": "⚠️",
    "CRITICAL": "🚨",
    "UNKNOWN": "❓",
}

REPORT_SYSTEM = """你是光纤维护报告撰写专家。
根据提供的分析结论，生成一份简洁专业的中文分析报告。

## 规则
1. 严格基于提供的数据，不编造任何数字
2. 结构：概述 → 详细发现 → 建议
3. 语言简洁专业，适合运维人员阅读
4. 不超过 300 字
"""


class ExpressionAgent(BaseAgent):
    """表达输出 Agent — 格式化 + LLM 报告 + 反幻觉."""

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.EXPRESSION

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        # 【用户记忆 [v7.4]】有 user_id 时注入输出格式偏好（零 LLM 开销；
        # 缺失时静默跳过，不改变默认行为）
        user_id = context.get("user_id") or ""
        if user_id:
            try:
                from ...memory.user_memory import get_user_memory_manager

                enriched = get_user_memory_manager().inject_preferences(user_id, {"output_format": plan.output_format})
                pref_format = enriched.get("output_format")
                if pref_format and pref_format in ("narrative", "table", "report", "raw"):
                    plan.output_format = pref_format
            except Exception as e:
                logger.warning(f"[ExpressionAgent] UserMemory inject failed: {e}")

        analysis_data = context.get("analysis_data", {})
        verdict = analysis_data.get("verdict", {})
        status = verdict.get("status", "UNKNOWN")
        findings = verdict.get("findings", [])
        suggestion = verdict.get("suggestion", "")

        # 根据 output_format 选择渲染方式
        fmt = plan.output_format
        degraded = False

        if fmt == "report":
            # LLM 报告生成路径
            output = await self._render_report_llm(verdict, context)
            if output is None:
                # LLM 失败 → 降级到模板
                output = self._render_narrative(status, findings, suggestion)
                degraded = True
        elif fmt == "raw":
            output = self._render_raw(verdict)
        elif fmt == "table":
            output = self._render_table(status, findings)
        else:
            output = self._render_narrative(status, findings, suggestion)

        # 反幻觉校验
        metrics = verdict.get("metrics", {})
        errors = validate_narration_numbers(output, metrics)
        hallucination_errors = []
        if errors:
            logger.warning(f"[ExpressionAgent] Hallucination detected: {errors}")
            hallucination_errors = errors
            # 降级到纯模板
            output = self._render_narrative(status, findings, suggestion)
            degraded = True

        # [P0] 输出侧护栏：PII 过滤 + 结构化验证
        guard_data = {"verdict": verdict, "response": output, "format": fmt}
        guard_verdict = run_output_guard(output, guard_data)
        if guard_verdict.warnings:
            logger.info(f"[ExpressionAgent] Output guard warnings: " f"{len(guard_verdict.warnings)}")
        if not guard_verdict.passed:
            # 护栏拦截 → 降级到安全输出
            logger.warning(f"[ExpressionAgent] Output guard blocked: " f"{guard_verdict.blocked_reason}")
            output = self._render_narrative(status, findings, "输出经过安全检查已简化呈现")
            degraded = True
            hallucination_errors = hallucination_errors + [f"guard_blocked: {guard_verdict.blocked_reason}"]
        elif guard_verdict.sanitized_output:
            output = guard_verdict.sanitized_output

        return AgentResult(
            layer=self.layer,
            success=True,
            data={
                "response": output,
                "format": fmt,
                "degraded": degraded,
                "hallucination_errors": hallucination_errors,
                "guard_warnings": guard_verdict.warnings,
            },
        )

    async def _render_report_llm(self, verdict: dict, context: dict) -> str | None:
        """LLM 报告生成（output_format='report'）."""
        breaker = get_llm_breaker()
        if not breaker.is_available:
            logger.info("[ExpressionAgent] Circuit open, skip LLM report")
            return None

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from ...llm.provider import get_report_llm

            llm = get_report_llm()
            user_msg = (
                f"## 分析结论\n"
                f"状态：{verdict.get('status', 'UNKNOWN')}\n"
                f"发现：{json.dumps(verdict.get('findings', []), ensure_ascii=False)}\n"
                f"建议：{verdict.get('suggestion', '')}\n\n"
                f"## 用户问题\n{context.get('user_input', '')}"
            )

            response = await llm.ainvoke(
                [
                    SystemMessage(content=REPORT_SYSTEM),
                    HumanMessage(content=user_msg),
                ]
            )

            content = response.content if hasattr(response, "content") else str(response)
            await breaker.record_success()
            return content.strip()

        except Exception as e:
            logger.warning(f"[ExpressionAgent] LLM report failed: {e}")
            await breaker.record_failure()
            return None

    def _render_narrative(self, status: str, findings: list, suggestion: str) -> str:
        """叙述式输出."""
        emoji = _STATUS_EMOJI.get(status, "❓")
        lines = [f"{emoji} 光纤状态：{status}"]
        if findings:
            lines.append("")
            for f in findings:
                # 支持 dict 和 str 两种格式
                if isinstance(f, dict):
                    lines.append(f"  • {f.get('description', str(f))}")
                else:
                    lines.append(f"  • {f}")
        if suggestion:
            lines.append(f"\n💡 建议：{suggestion}")
        return "\n".join(lines)

    def _render_table(self, status: str, findings: list) -> str:
        """表格式输出."""
        lines = [f"| 状态 | {status} |", "|---|---|"]
        for i, f in enumerate(findings, 1):
            desc = f.get("description", str(f)) if isinstance(f, dict) else str(f)
            lines.append(f"| 发现{i} | {desc} |")
        return "\n".join(lines)

    def _render_raw(self, verdict: dict) -> str:
        """原始 JSON 输出."""
        return json.dumps(verdict, ensure_ascii=False, indent=2)
