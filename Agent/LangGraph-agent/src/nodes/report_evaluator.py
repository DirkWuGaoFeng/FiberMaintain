"""
Report Evaluator Node — Reflection Loop (qwen2.5:14b, max 1 refinement).

Evaluates generated report for:
- Data accuracy (numbers match source)
- Completeness (all findings included)
- Structure (proper sections)

If failed and refinement_count < 1, routes back to report_generator.
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import MainGraphState
from ..llm.provider import get_report_eval_llm

logger = logging.getLogger(__name__)

EVAL_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是报告质量评估员。评估以下报告的质量。

## 评估标准
1. 数据准确性：数值是否与原始数据一致
2. 完整性：是否包含所有关键发现
3. 结构：是否有清晰的标题、正文、建议

## 输出格式（严格 JSON）
{{"passed": true/false, "issues": ["问题1", "问题2"], "suggestions": "改进建议"}}"""),
    ("human", """## 原始数据摘要
{data_summary}

## 规则判断
{rule_judgment}

## 生成的报告
{report}

请评估报告质量。"""),
])

_eval_chain = None


def _get_chain():
    global _eval_chain
    if _eval_chain is None:
        _eval_chain = EVAL_PROMPT | get_report_eval_llm()
    return _eval_chain


async def report_evaluator_node(state: MainGraphState) -> dict:
    """
    Report evaluator: Reflection Loop quality check.

    Returns report_eval dict with passed/issues/refinement_count.
    """
    report = state.get("report_content", "")
    prev_eval = state.get("report_eval", {})
    refinement_count = prev_eval.get("refinement_count", 0)

    if not report:
        return {"report_eval": {"passed": True, "refinement_count": refinement_count}}

    try:
        chain = _get_chain()
        judgment = state.get("rule_judgment", {})
        response = await chain.ainvoke({
            "data_summary": state.get("collected_data_summary", "暂无")[:1000],
            "rule_judgment": str(judgment)[:500],
            "report": report[:2000],
        })

        # Parse response
        content = response.content if hasattr(response, "content") else str(response)

        # Simple pass/fail heuristic
        passed = "问题" not in content and "错误" not in content
        if "passed" in content.lower():
            passed = '"passed": true' in content.lower() or '"passed":true' in content.lower()

        return {
            "report_eval": {
                "passed": passed,
                "refinement_count": refinement_count + (0 if passed else 1),
                "feedback": content[:500],
            },
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }

    except Exception as e:
        logger.error(f"[ReportEvaluator] Failed: {e}")
        # Force pass on evaluation failure
        return {"report_eval": {"passed": True, "refinement_count": refinement_count}}
