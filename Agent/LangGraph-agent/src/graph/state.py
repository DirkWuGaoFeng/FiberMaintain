"""
State definitions for the Fiber Maintenance Agent main graph and sub-graphs.

All states use TypedDict with LangGraph Annotated reducers.
Pydantic models enforce structured output via with_structured_output.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# =============================================================================
# Pydantic Structured Output Models
# =============================================================================

class IntentResult(BaseModel):
    """Intent classification result (enforced via with_structured_output)."""

    intent: Literal[
        "single_query",        # Single fiber query
        "batch_query",         # Batch fiber query
        "spanloss_analysis",   # Span loss analysis
        "color_diagnosis",     # Color diagnosis
        "trend_analysis",      # Trend analysis
        "health_check",        # NE health check
        "report_generation",   # Report generation
        "knowledge_qa",        # Knowledge Q&A
        "chitchat",            # Chitchat / fallback
    ] = Field(description="Identified user intent")
    fiber_ids: list[str] = Field(default=[], description="Extracted fiber IDs (FIB-XXXX)")
    ne_id: Optional[str] = Field(default=None, description="Network element ID")
    time_range: Optional[str] = Field(default=None, description="Time range for queries")
    confidence: float = Field(ge=0, le=1, description="Classification confidence")


class AnalysisResult(BaseModel):
    """Structured analysis conclusion from the analysis expert."""

    summary: str = Field(description="Brief analysis summary")
    fiber_id: Optional[str] = Field(default=None, description="Analyzed fiber ID")
    spanloss: Optional[float] = Field(default=None, description="Span loss value in dB")
    color: Optional[Literal["GREEN", "YELLOW", "RED"]] = Field(default=None, description="Fiber color status")
    anomalies: list[str] = Field(default=[], description="Detected anomalies")
    recommendations: list[str] = Field(default=[], description="Maintenance recommendations")
    severity: Literal["low", "medium", "high", "critical"] = Field(default="low", description="Issue severity")


class TaskPlan(BaseModel):
    """Task decomposition result."""

    subtasks: list[str] = Field(description="Ordered list of sub-tasks")
    strategy: Literal["single", "sequential", "parallel", "batch"] = Field(
        default="single", description="Execution strategy"
    )


# =============================================================================
# Main Graph State
# =============================================================================

class FiberAgentState(TypedDict):
    """Main orchestration graph state."""

    # Message stream (LangGraph standard with add_messages reducer)
    messages: Annotated[list[BaseMessage], add_messages]

    # Intent & task planning
    intent: Optional[IntentResult]
    task_plan: list[str]
    current_subtask_index: int

    # Data layer (raw data from Tools)
    fiber_data: dict
    alarm_data: dict
    performance_data: dict
    stats_data: dict

    # Analysis layer
    analysis_result: Optional[dict]
    diagnosis: Optional[str]

    # Batch layer
    batch_chunks: list[dict]
    batch_results: Annotated[list[dict], operator.add]  # Send concurrent results (reducer merge)
    batch_progress: dict  # {completed, total, percentage}

    # Knowledge layer
    rag_context: list[str]
    memory_context: list[dict]

    # Output layer
    final_report: Optional[str]
    export_path: Optional[str]

    # Control layer
    degradation_level: Literal["L1", "L2", "L3", "L4"]
    error_log: list[str]
    trace_id: str


# =============================================================================
# Sub-graph States
# =============================================================================

class DataCollectorState(TypedDict):
    """Data collector sub-graph state (ReAct Agent + ToolNode)."""

    messages: Annotated[list[BaseMessage], add_messages]
    fiber_ids: list[str]
    query_type: Literal["single", "batch", "performance", "alarm", "stats"]
    results: dict
    errors: list[str]
    retry_count: int


class BatchChunkState(TypedDict):
    """Single chunk state for Send dispatch unit."""

    chunk_id: str
    fiber_ids: list[str]  # <= 50 per chunk
    chunk_index: int
    result: Optional[dict]
    error: Optional[str]
    idempotency_key: str


class BatchAggregateState(TypedDict):
    """Aggregated batch result state."""

    total: int
    normal_count: int
    abnormal_count: int
    color_distribution: dict  # {green: n, yellow: n, red: n}
    spanloss_stats: dict  # {mean, max, min, std}
    top_anomalies: list[dict]  # Top-10 anomalies
    red_fibers: list[str]  # All red fiber IDs


# =============================================================================
# Default State Factory
# =============================================================================

def create_initial_state(user_message: str, trace_id: str = "") -> dict:
    """Create initial state for a new conversation turn."""
    import uuid
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=user_message)],
        "intent": None,
        "task_plan": [],
        "current_subtask_index": 0,
        "fiber_data": {},
        "alarm_data": {},
        "performance_data": {},
        "stats_data": {},
        "analysis_result": None,
        "diagnosis": None,
        "batch_chunks": [],
        "batch_results": [],
        "batch_progress": {},
        "rag_context": [],
        "memory_context": [],
        "final_report": None,
        "export_path": None,
        "degradation_level": "L1",
        "error_log": [],
        "trace_id": trace_id or uuid.uuid4().hex[:12],
    }
