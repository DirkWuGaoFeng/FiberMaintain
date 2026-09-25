"""
工具层导出 —— v8.0（23+ REST 工具 + 结构化返回）。

【工具分组】
  - topology_tools (5): 光纤连接查询、批量连接查询、场景查询、单盘查询、批量单盘查询
  - performance_tools (2): 光纤性能查询、跨段衰耗查询
  - fiber_tools (1): 光纤历史性能查询
  - alarm_tools (1): 告警查询
  - colored_tools (2): 颜色光纤查询、全色光纤查询
  - stats_tools (2): 光纤统计查询、趋势查询
  - board_tools (1): 单盘光纤查询
  - ne_tools (1): 网元查询
  - pullcall_tools (3): 工单创建、轮询、取消
  - batch_tools (4): 批量性能/衰耗/告警/连接查询
  - internal_tools (4): 事件/缓存/审计/系统健康
  - rag_tools (2): RAG 知识问答、知识搜索
  - export_tools (3): PDF/Excel/CSV 导出
  - memory_tools (2): 经验保存、经验查询
  - tool_result: 结构化工具返回类型 [P1-A]

【改进点 P1-A】
  新增 ToolResult 类型，所有工具可选择返回结构化结果而非纯字符串。
  新增 ToolExecutor 统一执行器，支持计时、异常捕获、JSON 自动解析。

【面试知识点】
  Q: 为什么工具层要分组？
  A: 不同子图需要不同的工具集。数据收集器只需要 REST 查询工具，
     分析专家只需要经验工具，报告生成器需要 RAG + 导出工具。
     分组实现了工具的最小权限原则。

  Q: ToolResult 的价值？
  A: 结构化返回使 LLM 节省 token（不需要解析 JSON 字符串），
     错误处理更明确，便于监控和审计。
"""

# ToolResult [P1-A]
# 拓扑工具
# HTTP 客户端（供节点直接使用）
from ._http_client import (
    CircuitOpenError,
    FiberHttpClient,
    assert_positive_int,
    assert_valid_color,
    fiber_http_client,
    make_error_json,
)

# 告警工具
from .alarm_tools import alarm_query

# 批量工具
from .batch_tools import (
    batch_alarm_query,
    batch_fiber_performance_query,
    batch_fiber_spanloss_query,
)
from .batch_tools import (
    batch_fiber_connection_query as batch_fiber_connection_query_tool,
)

# 单盘工具 [v7.1]
from .board_tools import board_fibers_query

# 代码编排工具 [P2，书籍 Ch5]
from .code_orchestrator import execute_code_plan

# 颜色光纤工具
from .colored_tools import (
    all_colored_fibers_query,
    colored_fibers_query,
)

# 导出工具
from .export_tools import export_csv, export_excel, export_pdf

# 光纤历史工具 [v7.1]
from .fiber_tools import fiber_history_performance

# 内部工具 [v7.1]
from .internal_tools import (
    audit_query,
    cache_query,
    event_query,
    system_health,
)

# 记忆工具
from .memory_tools import memory_query, memory_save

# 网元工具 [v7.1]
from .ne_tools import ne_query

# 性能工具
from .performance_tools import (
    fiber_performance_query,
    fiber_spanloss_query,
)

# 拉纤工具 [v7.1]
from .pullcall_tools import (
    pull_call_cancel,
    pull_call_create,
    pull_call_poll,
)

# RAG 工具
from .rag_tools import rag_query, rag_search

# 统计工具
from .stats_tools import (
    fiber_stats_query,
    fiber_trend_query,
)
from .tool_result import ToolExecutor, ToolResult, get_tool_executor
from .topology_tools import (
    batch_board_query,
    batch_fiber_connection_query,
    board_query,
    fiber_connection_query,
    fiber_scene_query,
)

__all__ = [
    # 工具结果 [P1-A]
    "ToolResult",
    "ToolExecutor",
    "get_tool_executor",
    # 拓扑
    "fiber_connection_query",
    "batch_fiber_connection_query",
    "fiber_scene_query",
    "board_query",
    "batch_board_query",
    # 性能
    "fiber_performance_query",
    "fiber_spanloss_query",
    "fiber_history_performance",
    # 告警
    "alarm_query",
    # 颜色
    "colored_fibers_query",
    "all_colored_fibers_query",
    # 统计
    "fiber_stats_query",
    "fiber_trend_query",
    # 单盘 [v7.1]
    "board_fibers_query",
    # 代码编排 [P2]
    "execute_code_plan",
    # 网元 [v7.1]
    "ne_query",
    # 拉纤 [v7.1]
    "pull_call_create",
    "pull_call_poll",
    "pull_call_cancel",
    # 批量
    "batch_fiber_performance_query",
    "batch_fiber_spanloss_query",
    "batch_alarm_query",
    "batch_fiber_connection_query_tool",
    # 内部 [v7.1]
    "event_query",
    "cache_query",
    "audit_query",
    "system_health",
    # RAG 检索
    "rag_query",
    "rag_search",
    # 导出
    "export_pdf",
    "export_excel",
    "export_csv",
    # 记忆
    "memory_save",
    "memory_query",
    # HTTP 客户端
    "fiber_http_client",
    "FiberHttpClient",
    "CircuitOpenError",
    "make_error_json",
    "assert_positive_int",
    "assert_valid_color",
]

# =============================================================================
# 工具分组 [v7.1]
# 【设计说明】每个子图绑定不同的工具集，实现最小权限原则
# =============================================================================

# 数据收集器工具集（P2：只有 data_collector 绑定后端 API 工具）
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

# 分析专家工具集（经验查询/写入，确定性优先原则 [P1-A]）
ANALYSIS_TOOLS = [
    memory_query,
    memory_save,
]

# 报告生成器工具集（RAG 知识 + 导出）
REPORT_TOOLS = [
    rag_query,
    export_pdf,
    export_excel,
    export_csv,
]

# 知识问答工具集（RAG + 经验）
KNOWLEDGE_TOOLS = [
    rag_query,
    rag_search,
    memory_query,
]

# 内部诊断工具集（不绑定到 data_collector）
INTERNAL_TOOLS = [
    event_query,
    cache_query,
    audit_query,
    system_health,
]

# 工单工具集（写操作由 ConfirmationGate 门禁保护 [P1-B]）
PULLCALL_TOOLS = [
    pull_call_create,
    pull_call_poll,
    pull_call_cancel,
]

# 代码编排工具集（书籍 Ch5 代码作为元能力；当前无在线节点绑定，
# 注册即可供未来 code_execution 路由启用）
CODING_TOOLS = [
    execute_code_plan,
]
