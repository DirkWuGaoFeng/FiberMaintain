"""
Analysis expert sub-graph: LLM reasoning + memory read/write.

Flow: load_memory -> analyze(LLM) -> save_memory
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from ...graph.state import AnalysisResult, FiberAgentState
from ...llm.provider import get_analysis_llm
from ...llm.prompts import ANALYSIS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def load_memory_node(state: FiberAgentState) -> dict:
    """Load relevant historical memory for the analysis."""
    intent = state.get("intent")
    fiber_ids = intent.fiber_ids if intent else []

    memory_context = []
    # Memory loading is handled by the memory tools if needed
    # Here we just prepare the context slot
    return {"memory_context": memory_context}


async def analyze_node(state: FiberAgentState) -> dict:
    """
    Core analysis node: temperature=0.1, deterministic priority.
    Analyzes fiber data and produces structured conclusions.
    """
    llm = get_analysis_llm()

    fiber_data = state.get("fiber_data", {})
    memory_context = state.get("memory_context", [])

    prompt = ChatPromptTemplate.from_messages([
        ("system", ANALYSIS_SYSTEM_PROMPT),
        ("human", """
## Fiber Data
{fiber_data}

## Historical Memory
{memory_context}

## Analysis Requirements
Please analyze the above data for span loss, color status, and performance anomalies.
Output structured conclusions.
"""),
    ])

    chain = prompt | llm.with_structured_output(AnalysisResult)

    try:
        result: AnalysisResult = await chain.ainvoke({
            "fiber_data": json.dumps(fiber_data, ensure_ascii=False)[:3000] if fiber_data else "No data",
            "memory_context": json.dumps(memory_context, ensure_ascii=False)[:1000] if memory_context else "No history",
        })

        return {
            "analysis_result": result.model_dump(),
            "diagnosis": result.summary,
        }
    except Exception as e:
        logger.error(f"[AnalysisExpert] Analysis failed: {e}")
        return {
            "analysis_result": {"summary": f"Analysis failed: {e}", "severity": "low"},
            "diagnosis": f"Analysis error: {e}",
            "error_log": [f"Analysis failed: {e}"],
        }


async def save_memory_node(state: FiberAgentState) -> dict:
    """Save analysis results to memory if significant findings."""
    # Memory saving is handled by memory_tools if needed
    # This node is a placeholder for the memory write step
    return {}


def build_analysis_subgraph():
    """Build the analysis expert sub-graph."""
    graph = StateGraph(FiberAgentState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("save_memory", save_memory_node)

    graph.add_edge(START, "load_memory")
    graph.add_edge("load_memory", "analyze")
    graph.add_edge("analyze", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile()


analysis_expert_subgraph = build_analysis_subgraph()
