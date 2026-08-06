"""
Intent Classifier Node — LLM intent recognition (qwen2.5:14b, Primary).

Uses with_structured_output for reliable JSON output.
Only invoked when rule engine misses (22% of queries).
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import IntentResult, MainGraphState
from ..llm.prompts import (
    INTENT_CLASSIFIER_PROMPT,
    escape_for_template,
    load_prompt,
)
from ..llm.provider import get_intent_llm

logger = logging.getLogger(__name__)

# 提示词唯一管理点：prompts/lead_agent/intent_classifier.md（AGENTS.md 约束）

_intent_chain = None


def _get_chain():
    global _intent_chain
    if _intent_chain is None:
        llm = get_intent_llm()
        system = escape_for_template(
            load_prompt("lead_agent", "intent_classifier", default=INTENT_CLASSIFIER_PROMPT)
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "{user_input}"),
        ])
        # json_mode: 百炼 thinking 模式拒绝 function_calling 的
        # tool_choice=required，改用 json_mode + 提示词约定 schema。
        _intent_chain = prompt | llm.with_structured_output(
            IntentResult, method="json_mode"
        )
    return _intent_chain


async def intent_classifier_node(state: MainGraphState) -> dict:
    """
    Intent classification node (14b primary model).

    Extracts user intent and key parameters.
    Uses with_structured_output to enforce IntentResult schema.
    """
    import time

    user_input = state.get("user_input", "")
    trace_id = state.get("trace_id", "")
    start_time = time.time()

    logger.info(f"[TRACE:{trace_id}] [intent_classifier] START input=\"{user_input[:80]}\"")

    try:
        chain = _get_chain()
        result: IntentResult = await chain.ainvoke({"user_input": user_input})
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(
            f"[TRACE:{trace_id}] [intent_classifier] OK {elapsed_ms}ms "
            f"intent={result.intent} confidence={result.confidence}"
        )
        return {
            "intent": result.intent,
            "intent_result": result.model_dump(),
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"[TRACE:{trace_id}] [intent_classifier] ERROR {elapsed_ms}ms error={e}")
        # Fallback to chitchat on failure
        return {
            "intent": "chitchat",
            "intent_result": IntentResult(intent="chitchat", confidence=0.0).model_dump(),
            "degradation_level": max(state.get("degradation_level", 0), 1),
        }
