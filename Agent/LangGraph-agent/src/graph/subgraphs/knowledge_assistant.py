"""
Knowledge assistant sub-graph: pure RAG retrieval + LLM answer.

Flow: retrieve -> answer
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from ...graph.state import FiberAgentState
from ...llm.provider import get_knowledge_llm
from ...llm.prompts import KNOWLEDGE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def rag_retrieve_node(state: FiberAgentState) -> dict:
    """Retrieve relevant knowledge chunks."""
    # RAG retrieval is handled by rag_tools
    return {}


async def knowledge_answer_node(state: FiberAgentState) -> dict:
    """Generate answer from knowledge base context."""
    llm = get_knowledge_llm()

    user_query = state["messages"][-1].content if state["messages"] else ""
    rag_context = state.get("rag_context", [])

    prompt = ChatPromptTemplate.from_messages([
        ("system", KNOWLEDGE_SYSTEM_PROMPT),
        ("human", """
## Knowledge Base Context
{rag_context}

## User Question
{user_query}

Please answer based on the knowledge base. If the answer is not available, say so clearly.
"""),
    ])

    chain = prompt | llm

    try:
        result = await chain.ainvoke({
            "rag_context": "\n\n".join(rag_context[:3]) if rag_context else "No relevant knowledge found",
            "user_query": user_query,
        })

        answer = result.content if hasattr(result, "content") else str(result)
        return {
            "messages": [AIMessage(content=answer)],
            "final_report": answer,
        }
    except Exception as e:
        logger.error(f"[KnowledgeAssistant] Answer generation failed: {e}")
        error_msg = f"Knowledge query failed: {e}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "final_report": error_msg,
        }


def build_knowledge_subgraph():
    """Build the knowledge assistant sub-graph."""
    graph = StateGraph(FiberAgentState)

    graph.add_node("retrieve", rag_retrieve_node)
    graph.add_node("answer", knowledge_answer_node)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)

    return graph.compile()


knowledge_assistant_subgraph = build_knowledge_subgraph()
