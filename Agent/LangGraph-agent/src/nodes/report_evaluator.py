"""
报告评估节点 —— 确定性清单（硬门）+ LLM 表达质量评估（低权重）。

【设计变更 v7.2】（书籍 Ch6 确定性检查先行 + Ch10 同模型自我审查无效）
- 旧版：纯 LLM 自评（与生成器同家族模型），判定为脆弱的字符串启发式
- 新版两段式：
  1. 确定性清单（数字溯源 / 章节齐全 / severity 一致）—— 任一项失败直接 veto
  2. LLM 仅评"表达质量"单一维度（低权重），不再是唯一裁判
  3. LLM 不可用时以确定性清单结果为准（清单全过即放行，不掩盖失败）

【反思循环】
未通过且 refinement_count < 1 时路由回 report_generator，
feedback 为结构化失败项清单，供生成器定向修正。

【面试知识点】
  Q: 为什么不让 LLM 直接判 passed？
  A: 书籍 Ch10：等计算量下同一模型自我审查通常无效。数字溯源、
     章节齐全、severity 一致性都是可形式化规则，代码校验 100%
     可靠且零成本；LLM 只保留难以形式化的表达质量维度。
"""

from __future__ import annotations

import json
import logging

from langchain_core.prompts import ChatPromptTemplate

from ..governance.report_checklist import run_report_checklist
from ..graph.state import MainGraphState
from ..llm.provider import get_report_eval_llm

logger = logging.getLogger(__name__)

# LLM 仅评估表达质量（数据准确性/结构已由确定性清单覆盖，禁止重复判断）
EVAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是报告表达质量评估员。只评估表达质量这一个维度。
数据准确性与结构完整性已由其他系统校验，不要重复判断。
关注点：语句不通、术语误用、章节逻辑混乱、冗余啰嗦。

## 输出格式（严格 JSON）
{{"expression_ok": true/false, "issues": ["问题1"]}}

仅当表达明显影响阅读时才输出 false，小瑕疵一律通过。""",
        ),
        (
            "human",
            """## 生成的报告
{report}

请评估表达质量。""",
        ),
    ]
)

_eval_chain = None


def _get_chain():
    global _eval_chain
    if _eval_chain is None:
        _eval_chain = EVAL_PROMPT | get_report_eval_llm()
    return _eval_chain


def _parse_expression_ok(content: str) -> tuple[bool, str]:
    """宽松解析表达质量评估结果，返回 (是否通过, 反馈文本)。"""
    try:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(content[start : end + 1])
            issues = data.get("issues") or []
            return bool(data.get("expression_ok", True)), "; ".join(str(i) for i in issues)
    except (json.JSONDecodeError, AttributeError):
        pass
    # 兜底启发式：仅显式 false 才判不通过
    if '"expression_ok": false' in content.lower() or '"expression_ok":false' in content.lower():
        return False, content[:200]
    return True, ""


async def report_evaluator_node(state: MainGraphState) -> dict:
    """报告评估节点：确定性硬门 + 表达质量评估。

    【输入】state.report_content, state.collected_data_summary,
            state.rule_judgment, state.analysis_verdict
    【输出】report_eval（{"passed": bool, "refinement_count": int,
            "feedback": str, "checklist": list}）
    """
    report = state.get("report_content", "")
    prev_eval = state.get("report_eval", {})
    refinement_count = prev_eval.get("refinement_count", 0)

    if not report:
        return {"report_eval": {"passed": True, "refinement_count": refinement_count}}

    # 第一段：确定性清单（零 LLM，任一失败即 veto）
    checklist = run_report_checklist(
        report,
        state.get("collected_data_summary") or "",
        state.get("rule_judgment") or {},
        state.get("analysis_verdict"),
    )
    failed = [c for c in checklist if not c["passed"]]
    if failed:
        feedback = "\n".join(f"- [{c['check']}] {c['evidence']}" for c in failed)
        logger.info(f"[ReportEvaluator] checklist veto: {len(failed)} item(s) failed")
        return {
            "report_eval": {
                "passed": False,
                "refinement_count": refinement_count + 1,
                "feedback": feedback,
                "checklist": checklist,
            }
        }

    # 第二段：LLM 仅评表达质量（低权重，失败不阻塞）
    try:
        chain = _get_chain()
        response = await chain.ainvoke({"report": report[:3000]})
        content = response.content if hasattr(response, "content") else str(response)
        expression_ok, issues = _parse_expression_ok(content)
        return {
            "report_eval": {
                "passed": expression_ok,
                "refinement_count": refinement_count + (0 if expression_ok else 1),
                "feedback": issues if not expression_ok else "",
                "checklist": checklist,
            },
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }
    except Exception as e:
        # LLM 不可用：确定性清单已全部通过，放行（不掩盖清单失败）
        logger.warning(f"[ReportEvaluator] Expression eval skipped (LLM failed): {e}")
        return {
            "report_eval": {
                "passed": True,
                "refinement_count": refinement_count,
                "feedback": "",
                "checklist": checklist,
            }
        }
