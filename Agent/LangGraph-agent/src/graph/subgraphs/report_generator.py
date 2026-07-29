"""
Report generator sub-graph: RAG retrieval + LLM generation + export.

Flow: rag_retrieve -> generate_report -> export_file (conditional)
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from ...graph.state import FiberAgentState
from ...llm.provider import get_report_llm
from ...llm.prompts import REPORT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def rag_retrieve_node(state: FiberAgentState) -> dict:
    """Retrieve relevant knowledge for report enhancement."""
    # RAG retrieval is handled by rag_tools
    # This node prepares the context slot
    return {}


async def generate_report_node(state: FiberAgentState) -> dict:
    """Generate the maintenance report using LLM."""
    llm = get_report_llm()

    fiber_data = state.get("fiber_data", {})
    analysis = state.get("analysis_result", {})
    rag_context = state.get("rag_context", [])

    prompt = ChatPromptTemplate.from_messages([
        ("system", REPORT_SYSTEM_PROMPT),
        ("human", """
## Analysis Results
{analysis}

## Fiber Data
{fiber_data}

## Reference Knowledge
{rag_context}

Generate a comprehensive maintenance report in Markdown format.
"""),
    ])

    chain = prompt | llm

    try:
        result = await chain.ainvoke({
            "analysis": json.dumps(analysis, ensure_ascii=False)[:2000] if analysis else "No analysis",
            "fiber_data": json.dumps(fiber_data, ensure_ascii=False)[:2000] if fiber_data else "No data",
            "rag_context": "\n".join(rag_context[:3]) if rag_context else "No reference knowledge",
        })

        report = result.content if hasattr(result, "content") else str(result)
        return {
            "messages": [AIMessage(content=report)],
            "final_report": report,
        }
    except Exception as e:
        logger.error(f"[ReportGenerator] Report generation failed: {e}")
        error_report = f"Report generation failed: {e}"
        return {
            "messages": [AIMessage(content=error_report)],
            "final_report": error_report,
            "error_log": [f"Report generation failed: {e}"],
        }


async def export_file_node(state: FiberAgentState) -> dict:
    """Export the report to file if requested."""
    # Export is handled by export_tools when needed
    return {}


def _should_export(state: FiberAgentState) -> str:
    """Check if export is needed."""
    # For now, export is opt-in via tools
    return "end"


def build_report_subgraph():
    """Build the report generator sub-graph."""
    graph = StateGraph(FiberAgentState)

    graph.add_node("rag_retrieve", rag_retrieve_node)
    graph.add_node("generate_report", generate_report_node)
    graph.add_node("export_file", export_file_node)

    graph.add_edge(START, "rag_retrieve")
    graph.add_edge("rag_retrieve", "generate_report")
    graph.add_conditional_edges(
        "generate_report",
        _should_export,
        {"export": "export_file", "end": END},
    )
    graph.add_edge("export_file", END)

    return graph.compile()


report_generator_subgraph = build_report_subgraph()
