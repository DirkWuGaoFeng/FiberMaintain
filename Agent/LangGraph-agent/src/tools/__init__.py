"""
Tool layer exports - all 18+ tools for the Fiber Maintenance Agent.

Tools are organized by domain:
  - topology_tools (5): fiber_connection_query, batch_fiber_connection_query,
                         fiber_scene_query, board_query, batch_board_query
  - performance_tools (2): fiber_performance_query, fiber_spanloss_query
  - alarm_tools (1): alarm_query
  - colored_tools (2): colored_fibers_query, all_colored_fibers_query
  - stats_tools (2): fiber_stats_query, fiber_trend_query
  - batch_tools (4): batch_fiber_performance_query, batch_fiber_spanloss_query,
                      batch_alarm_query, batch_fiber_connection_query
  - rag_tools (2): rag_query, rag_search
  - export_tools (3): export_pdf, export_excel, export_csv
  - memory_tools (2): memory_save, memory_query
"""

# Topology tools
from .topology_tools import (
    board_query,
    batch_board_query,
    batch_fiber_connection_query,
    fiber_connection_query,
    fiber_scene_query,
)

# Performance tools
from .performance_tools import (
    fiber_performance_query,
    fiber_spanloss_query,
)

# Alarm tools
from .alarm_tools import alarm_query

# Colored fiber tools
from .colored_tools import (
    all_colored_fibers_query,
    colored_fibers_query,
)

# Stats tools
from .stats_tools import (
    fiber_stats_query,
    fiber_trend_query,
)

# Batch tools
from .batch_tools import (
    batch_alarm_query,
    batch_fiber_connection_query as batch_fiber_connection_query_tool,
    batch_fiber_performance_query,
    batch_fiber_spanloss_query,
)

# RAG tools
from .rag_tools import rag_query, rag_search

# Export tools
from .export_tools import export_csv, export_excel, export_pdf

# Memory tools
from .memory_tools import memory_query, memory_save

# HTTP client (for direct use in nodes)
from ._http_client import fiber_http_client, FiberHttpClient, CircuitOpenError

__all__ = [
    # Topology
    "fiber_connection_query",
    "batch_fiber_connection_query",
    "fiber_scene_query",
    "board_query",
    "batch_board_query",
    # Performance
    "fiber_performance_query",
    "fiber_spanloss_query",
    # Alarm
    "alarm_query",
    # Colored
    "colored_fibers_query",
    "all_colored_fibers_query",
    # Stats
    "fiber_stats_query",
    "fiber_trend_query",
    # Batch
    "batch_fiber_performance_query",
    "batch_fiber_spanloss_query",
    "batch_alarm_query",
    "batch_fiber_connection_query_tool",
    # RAG
    "rag_query",
    "rag_search",
    # Export
    "export_pdf",
    "export_excel",
    "export_csv",
    # Memory
    "memory_save",
    "memory_query",
    # HTTP Client
    "fiber_http_client",
    "FiberHttpClient",
    "CircuitOpenError",
]

# Data collector tools list (P2: only data_collector binds backend API tools)
DATA_COLLECTOR_TOOLS = [
    fiber_connection_query,
    batch_fiber_connection_query,
    fiber_scene_query,
    board_query,
    batch_board_query,
    fiber_performance_query,
    fiber_spanloss_query,
    colored_fibers_query,
    all_colored_fibers_query,
    fiber_stats_query,
    fiber_trend_query,
    alarm_query,
]

# Analysis expert tools
ANALYSIS_TOOLS = [
    memory_query,
    memory_save,
]

# Report generator tools
REPORT_TOOLS = [
    rag_query,
    export_pdf,
    export_excel,
    export_csv,
]

# Knowledge assistant tools
KNOWLEDGE_TOOLS = [
    rag_query,
    rag_search,
    memory_query,
]
