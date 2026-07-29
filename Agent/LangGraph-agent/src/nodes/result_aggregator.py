"""
Result aggregator node: generates the final natural language response.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import FiberAgentState
from ..llm.provider import get_llm_with_fallback
from ..llm.prompts import RESULT_AGGREGATOR_PROMPT

logger = logging.getLogger(__name__)


async def result_aggregator_node(state: FiberAgentState) -> dict:
    """
    Result aggregator: synthesizes analysis results into a user-facing response.
    If degradation_level is L3/L4, uses template-based response instead of LLM.
    """
    # Check for degradation modes
    level = state.get("degradation_level", "L1")
    if level in ("L3", "L4"):
        # Skip LLM, use template
        report = state.get("final_report", "")
        if not report:
            report = _generate_template_response(state)
        return {
            "messages": [AIMessage(content=report)],
            "final_report": report,
        }

    # Normal LLM-based aggregation
    intent = state.get("intent")
    fiber_data = state.get("fiber_data", {})
    analysis = state.get("analysis_result", {})
    diagnosis = state.get("diagnosis", "")

    # For chitchat, pass through directly
    if intent and intent.intent == "chitchat":
        last_msg = state["messages"][-1] if state["messages"] else None
        if last_msg and isinstance(last_msg, AIMessage):
            return {"final_report": last_msg.content}

    try:
        llm = get_llm_with_fallback(temperature=0.3)
        prompt = ChatPromptTemplate.from_messages([
            ("system", RESULT_AGGREGATOR_PROMPT),
            ("human", """
## User Query
{user_query}

## Analysis Result
{analysis}

## Fiber Data Summary
{fiber_data}

## Diagnosis
{diagnosis}

Please provide a clear, actionable response.
"""),
        ])

        chain = prompt | llm
        result = await chain.ainvoke({
            "user_query": state["messages"][-1].content if state["messages"] else "",
            "analysis": str(analysis) if analysis else "No analysis available",
            "fiber_data": str(fiber_data)[:2000] if fiber_data else "No data",
            "diagnosis": diagnosis or "No diagnosis",
        })

        report = result.content if hasattr(result, "content") else str(result)
        return {
            "messages": [AIMessage(content=report)],
            "final_report": report,
        }

    except Exception as e:
        logger.error(f"[ResultAggregator] LLM failed: {e}")
        report = _generate_template_response(state)
        return {
            "messages": [AIMessage(content=report)],
            "final_report": report,
        }


def _generate_template_response(state: FiberAgentState) -> str:
    """Generate a template-based response for degradation modes."""
    intent = state.get("intent")
    fiber_data = state.get("fiber_data", {})

    if not fiber_data:
        return "I've processed your request. The system is currently in a limited mode. Please try again later."

    total = fiber_data.get("total", 0)
    normal = fiber_data.get("normal", 0)
    abnormal = fiber_data.get("abnormal", 0)

    return f"""## Query Results

- **Total fibers processed**: {total}
- **Normal**: {normal}
- **Abnormal**: {abnormal}

> Note: System is operating in degraded mode. Some analysis capabilities may be limited.
"""
