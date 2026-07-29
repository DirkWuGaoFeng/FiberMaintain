"""
Intent classifier node: uses with_structured_output for reliable JSON output.
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import FiberAgentState, IntentResult
from ..llm.provider import get_intent_llm
from ..llm.prompts import INTENT_CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)


def _build_intent_chain():
    """Build the intent classification chain."""
    llm = get_intent_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", INTENT_CLASSIFIER_PROMPT),
        ("human", "{user_input}"),
    ])
    return prompt | llm.with_structured_output(IntentResult)


# Lazy-initialized chain
_intent_chain = None


def _get_chain():
    global _intent_chain
    if _intent_chain is None:
        _intent_chain = _build_intent_chain()
    return _intent_chain


async def intent_classifier_node(state: FiberAgentState) -> dict:
    """
    Intent classification node.
    Extracts user intent and key parameters (fiber_ids, ne_id, time_range).
    Uses with_structured_output to enforce IntentResult schema.
    """
    user_msg = state["messages"][-1].content if state["messages"] else ""
    logger.info(f"[IntentClassifier] Classifying: {user_msg[:100]}")

    try:
        chain = _get_chain()
        result: IntentResult = await chain.ainvoke({"user_input": user_msg})
        logger.info(f"[IntentClassifier] Result: intent={result.intent}, confidence={result.confidence}")
        return {"intent": result}
    except Exception as e:
        logger.error(f"[IntentClassifier] Failed: {e}")
        # Fallback to chitchat on failure
        fallback = IntentResult(intent="chitchat", confidence=0.0)
        return {"intent": fallback, "error_log": [f"Intent classification failed: {e}"]}
