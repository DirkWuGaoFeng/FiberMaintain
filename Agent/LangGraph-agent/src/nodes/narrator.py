"""
Narrator Node — LLM expression (qwen2.5:7b, Secondary).

LLM's ONLY job: translate structured judgment into natural language.
Hard constraints:
- Must NOT modify any numeric values
- Must NOT add conclusions not in the judgment
- Must NOT fabricate data
- Must NOT change severity level

Uses secondary model (7b) — expression tasks don't need 14b reasoning.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import MainGraphState
from ..governance.number_validator import validate_narration_numbers
from ..llm.provider import get_narrator_llm

logger = logging.getLogger(__name__)

NARRATOR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是光纤维护报告的叙述员。

## 你的唯一职责
将以下【结构化判断】转换为通顺的自然语言回答。

## 硬约束（违反任何一条即为失败）
1. 不得修改任何数值（如 3.2dB 不能写成"约3dB"）
2. 不得添加判断中没有的结论
3. 不得编造数据
4. 不得改变严重程度判断（NORMAL/WARNING/CRITICAL）
5. 可以调整语序、增加连接词、使表述更自然

## 输出格式
直接用自然语言回答用户问题，200字以内。"""),
    ("human", """## 用户问题
{question}

## 结构化判断（不可修改）
状态: {status}
发现:
{findings}
关键指标: {metrics}
建议操作: {actions}

请将以上判断转换为自然语言回答。"""),
])

# Lazy-initialized chain
_narrator_chain = None


def _get_chain():
    global _narrator_chain
    if _narrator_chain is None:
        _narrator_chain = NARRATOR_PROMPT | get_narrator_llm()
    return _narrator_chain


async def narrator_node(state: MainGraphState) -> dict:
    """
    Narrator: translate structured judgment to natural language. Uses 7b model.

    Output saved to state["narration"] for NarratorValidator [v7.1].
    """
    judgment = state.get("rule_judgment")

    if not judgment:
        fallback_msg = "暂无分析结果。"
        return {
            "messages": [AIMessage(content=fallback_msg)],
            "narration": fallback_msg,
            "final_output": fallback_msg,
        }

    try:
        chain = _get_chain()
        response = await chain.ainvoke({
            "question": state.get("user_input", ""),
            "status": judgment.get("status", "UNKNOWN"),
            "findings": "\n".join(f"  • {f}" for f in judgment.get("findings", [])),
            "metrics": str(judgment.get("metrics", {})),
            "actions": "、".join(judgment.get("suggested_actions", [])) or "无",
        })

        narration = response.content if hasattr(response, "content") else str(response)

        # 数字幻觉校验 [governance]
        source_numbers = dict(judgment.get("metrics", {}))
        hallucination_errors = validate_narration_numbers(narration, source_numbers)
        if hallucination_errors:
            logger.warning(f"[Narrator] Number hallucination detected: {hallucination_errors}")
            # 降级到模板输出（不使用 LLM 结果）
            findings = judgment.get("findings", [])
            status = judgment.get("status", "UNKNOWN")
            narration = f"📊 光纤状态：{status}\n" + "\n".join(f"  • {f}" for f in findings)

        return {
            "messages": [AIMessage(content=narration)],
            "narration": narration,  # [v7.1] Save for validator
            "final_output": narration,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }

    except Exception as e:
        logger.error(f"[Narrator] LLM failed: {e}, using template fallback")
        # Fallback: simple template output
        findings = judgment.get("findings", [])
        status = judgment.get("status", "UNKNOWN")
        fallback = f"📊 光纤状态：{status}\n" + "\n".join(f"  • {f}" for f in findings)
        return {
            "messages": [AIMessage(content=fallback)],
            "narration": fallback,
            "final_output": fallback,
            "degradation_level": max(state.get("degradation_level", 0), 1),
        }
