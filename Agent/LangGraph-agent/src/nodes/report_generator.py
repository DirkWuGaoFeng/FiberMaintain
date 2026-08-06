"""
Report Generator Node — Structured report generation (qwen2.5:14b, Primary).

Generates maintenance reports based on collected data and analysis.
Uses Reflection Loop with report_evaluator (max 1 refinement).
"""

from __future__ import annotations

import logging
from datetime import datetime

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import MainGraphState
from ..llm.provider import get_report_llm

logger = logging.getLogger(__name__)

REPORT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是光纤维护报告生成专家。根据数据和分析结论生成结构化报告。

## 报告格式
# 光纤维护报告

## 概要
（一句话总结）

## 详细分析
（数据发现、异常说明）

## 建议措施
（操作建议，按优先级排列）

## 数据附录
（关键数值表格）

## 规则
1. 所有数值必须来自提供的数据，不得编造
2. 建议必须具体可操作
3. 语言简洁专业，500字以内"""),
    ("human", """## 用户请求
{question}

## 数据摘要
{data_summary}

## 规则判断
{rule_judgment}

## 分析结论
{analysis}

{refinement_instruction}

请生成报告。"""),
])

_report_chain = None


def _get_chain():
    global _report_chain
    if _report_chain is None:
        _report_chain = REPORT_PROMPT | get_report_llm()
    return _report_chain


async def report_generator_node(state: MainGraphState) -> dict:
    """
    Report generator: create structured maintenance report. Uses 14b model.
    """
    prev_eval = state.get("report_eval", {})
    is_refinement = prev_eval.get("refinement_count", 0) > 0

    refinement_instruction = ""
    if is_refinement and prev_eval.get("feedback"):
        refinement_instruction = f"## 修改要求（上一版问题）\n{prev_eval['feedback']}"

    judgment = state.get("rule_judgment", {})
    verdict = state.get("analysis_verdict", {})

    try:
        chain = _get_chain()
        response = await chain.ainvoke({
            "question": state.get("user_input", "生成维护报告"),
            "data_summary": (state.get("collected_data_summary", "") or "暂无")[:1500],
            "rule_judgment": str(judgment)[:500] if judgment else "无",
            "analysis": str(verdict)[:500] if verdict else "无",
            "refinement_instruction": refinement_instruction,
        })

        report = response.content if hasattr(response, "content") else str(response)

        return {
            "report_content": report,
            "messages": [AIMessage(content=report)],
            "final_output": report,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
            "processing_path": "heavy",
        }

    except Exception as e:
        logger.error(f"[ReportGenerator] LLM failed: {e}")
        # Template fallback for report
        report = _template_report(state)
        return {
            "report_content": report,
            "messages": [AIMessage(content=report)],
            "final_output": report,
            "processing_path": "degraded",
        }


def _template_report(state: MainGraphState) -> str:
    """Generate template-based report when LLM unavailable."""
    judgment = state.get("rule_judgment", {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 光纤维护报告",
        f"\n生成时间：{now}",
        "\n## 概要",
        f"状态：{judgment.get('status', 'UNKNOWN')}",
        "\n## 详细发现",
    ]
    for f in judgment.get("findings", ["无数据"]):
        lines.append(f"- {f}")

    lines.append("\n## 建议措施")
    for a in judgment.get("suggested_actions", ["暂无建议"]):
        lines.append(f"- {a}")

    lines.append("\n\n⚠️ （本报告由模板引擎生成，LLM 服务暂不可用）")
    return "\n".join(lines)
