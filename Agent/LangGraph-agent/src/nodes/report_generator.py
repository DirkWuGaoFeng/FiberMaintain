"""
报告生成节点 —— 结构化报告生成（使用 qwen2.5:14b 主模型）。

【功能说明】
根据收集的数据和分析结论生成维护报告。
使用反思循环（Reflection Loop）：生成 → 评估 → 优化（最多 1 次）。

【架构位置】
  分析专家 → 【报告生成】 → 报告评估 → 输出/优化

【面试知识点】
  Q: 什么是反思循环（Reflection Loop）？
  A: Agent 的高级模式：生成结果 → 自我评估 → 根据反馈优化。
     类似人类的「写草稿 → 检查 → 修改」过程。
     限制最多 1 次优化，防止死循环。
"""

from __future__ import annotations

import logging
from datetime import datetime

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import MainGraphState
from ..llm.provider import get_report_llm

logger = logging.getLogger(__name__)

# 报告生成提示词（已是中文）
REPORT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是光纤维护报告生成专家。根据数据和分析结论生成结构化报告。

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
3. 语言简洁专业，500字以内""",
        ),
        (
            "human",
            """## 用户请求
{question}

## 数据摘要
{data_summary}

## 规则判断
{rule_judgment}

## 分析结论
{analysis}

{refinement_instruction}

请生成报告。""",
        ),
    ]
)

# 懒加载的报告链（首次调用时初始化）
_report_chain = None


def _get_chain():
    """获取报告链（懒加载单例）。"""
    global _report_chain
    if _report_chain is None:
        _report_chain = REPORT_PROMPT | get_report_llm()
    return _report_chain


async def report_generator_node(state: MainGraphState) -> dict:
    """报告生成节点 —— 生成结构化维护报告（使用 14b 主模型）。

    【输入】
        state: 主图状态，包含数据摘要、规则判断、分析结论

    【输出】
        包含 report_content、final_output 的状态字典

    【反思循环】
    如果上一轮评估反馈了问题，会包含 refinement_instruction 要求优化。
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
        response = await chain.ainvoke(
            {
                "question": state.get("user_input", "生成维护报告"),
                "data_summary": (state.get("collected_data_summary", "") or "暂无")[:1500],
                "rule_judgment": str(judgment)[:500] if judgment else "无",
                "analysis": str(verdict)[:500] if verdict else "无",
                "refinement_instruction": refinement_instruction,
            }
        )

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
        # 报告的模板兜底方案
        report = _template_report(state)
        return {
            "report_content": report,
            "messages": [AIMessage(content=report)],
            "final_output": report,
            "processing_path": "degraded",
        }


def _template_report(state: MainGraphState) -> str:
    """基于模板生成报告（LLM 不可用时的兆底方案）。"""
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
