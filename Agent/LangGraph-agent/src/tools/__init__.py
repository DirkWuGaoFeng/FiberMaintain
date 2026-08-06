"""
Tool layer exports — v7.1-Final (23+ REST Tools).

Tools are organized by domain:
  - topology_tools (5): fiber_connection_query, batch_fiber_connection_query,
                         fiber_scene_query, board_query, batch_board_query
  - performance_tools (2): fiber_performance_query, fiber_spanloss_query
  - fiber_tools (1): fiber_history_performance
  - alarm_tools (1): alarm_query
  - colored_tools (2): colored_fibers_query, all_colored_fibers_query
  - stats_tools (2): fiber_stats_query, fiber_trend_query
  - board_tools (1): board_fibers_query
  - ne_tools (1): ne_query
  - pullcall_tools (3): pull_call_create, pull_call_poll, pull_call_cancel
  - batch_tools (4): batch_fiber_performance_query, batch_fiber_spanloss_query,
                      batch_alarm_query, batch_fiber_connection_query
  - internal_tools (4): event_query, cache_query, audit_query, system_health
  - rag_tools (2): rag_query, rag_search
  - export_tools (3): export_pdf, export_excel, export_csv
  - memory_tools (2): memory_save, memory_query
"""

# Topology tools
# HTTP client (for direct use in nodes)
from ._http_client import (
    CircuitOpenError,
    FiberHttpClient,
    assert_positive_int,
    assert_valid_color,
    fiber_http_client,
    make_error_json,
)

# Alarm tools
from .alarm_tools import alarm_query

# Batch tools
from .batch_tools import (
    batch_alarm_query,
    batch_fiber_performance_query,
    batch_fiber_spanloss_query,
)
from .batch_tools import (
    batch_fiber_connection_query as batch_fiber_connection_query_tool,
)

# Board tools [v7.1]
from .board_tools import board_fibers_query

# Colored fiber tools
from .colored_tools import (
    all_colored_fibers_query,
    colored_fibers_query,
)

# Export tools
from .export_tools import export_csv, export_excel, export_pdf

# Fiber history tools [v7.1]
from .fiber_tools import fiber_history_performance

# Internal tools [v7.1]
from .internal_tools import (
    audit_query,
    cache_query,
    event_query,
    system_health,
)

# Memory tools
from .memory_tools import memory_query, memory_save

# NE tools [v7.1]
from .ne_tools import ne_query

# Performance tools
from .performance_tools import (
    fiber_performance_query,
    fiber_spanloss_query,
)

# Pull-call tools [v7.1]
from .pullcall_tools import (
    pull_call_cancel,
    pull_call_create,
    pull_call_poll,
)

# RAG tools
from .rag_tools import rag_query, rag_search

# Stats tools
from .stats_tools import (
    fiber_stats_query,
    fiber_trend_query,
)
from .topology_tools import (
    batch_board_query,
    batch_fiber_connection_query,
    board_query,
    fiber_connection_query,
    fiber_scene_query,
)

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
    "fiber_history_performance",
    # Alarm
    "alarm_query",
    # Colored
    "colored_fibers_query",
    "all_colored_fibers_query",
    # Stats
    "fiber_stats_query",
    "fiber_trend_query",
    # Board [v7.1]
    "board_fibers_query",
    # NE [v7.1]
    "ne_query",
    # Pull-call [v7.1]
    "pull_call_create",
    "pull_call_poll",
    "pull_call_cancel",
    # Batch
    "batch_fiber_performance_query",
    "batch_fiber_spanloss_query",
    "batch_alarm_query",
    "batch_fiber_connection_query_tool",
    # Internal [v7.1]
    "event_query",
    "cache_query",
    "audit_query",
    "system_health",
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
    "make_error_json",
    "assert_positive_int",
    "assert_valid_color",
]

# =============================================================================
# Tool Groups [v7.1]
# =============================================================================

# Data collector tools (P2: only data_collector binds backend API tools)
DATA_COLLECTOR_TOOLS = [
    fiber_connection_query,
    batch_fiber_connection_query,
    fiber_scene_query,
    board_query,
    batch_board_query,
    board_fibers_query,
    fiber_performance_query,
    fiber_spanloss_query,
    fiber_history_performance,
    colored_fibers_query,
    all_colored_fibers_query,
    fiber_stats_query,
    fiber_trend_query,
    alarm_query,
    ne_query,
    # Pull-call [P1-B]: 写工具已接入确认门禁，无 confirm_token 仅登记待确认
    pull_call_create,
    pull_call_poll,
    pull_call_cancel,
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

# Internal diagnostics tools (not bound to data_collector)
INTERNAL_TOOLS = [
    event_query,
    cache_query,
    audit_query,
    system_health,
]

# Pull-call tools (写操作由 ConfirmationGate 门禁保护 [P1-B])
PULLCALL_TOOLS = [
    pull_call_create,
    pull_call_poll,
    pull_call_cancel,
]
