"""Prometheus 指标定义（§13.2）。"""
from prometheus_client import Counter, Histogram, Gauge

# ── Agent 层 ──
AGENT_REQUESTS = Counter("agent_request_total", "Agent 请求总数", ["status"])
AGENT_REQUEST_DURATION = Histogram(
    "agent_request_duration_seconds", "请求响应时间",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120))
TOOL_CALLS = Counter("agent_tool_call_total", "工具调用次数", ["tool", "status"])
TOOL_ERRORS = Counter("agent_tool_call_errors_total", "工具调用失败", ["tool"])
LLM_TOKENS = Counter("agent_llm_tokens_total", "Token 消耗", ["direction"])
LLM_LATENCY = Histogram("agent_llm_latency_seconds", "LLM 推理延迟",
                        buckets=(0.5, 1, 2, 5, 10, 20, 40))
MODEL_DEGRADATION = Counter("agent_model_degradation_total", "模型降级次数",
                            ["level"])
SUBAGENT_CONCURRENT = Gauge("agent_subagent_concurrent", "当前并发 Sub-Agent 数")
SUBAGENT_QUEUE = Gauge("agent_subagent_queued", "FIFO 队列排队任务数")
RAG_DURATION = Histogram("agent_rag_query_duration_seconds", "RAG 检索延迟",
                         buckets=(0.05, 0.1, 0.25, 0.5, 1, 2))

# ── MCP 层 ──
MCP_CALLS = Counter("mcp_call_total", "MCP 调用次数", ["method", "path", "status"])
MCP_ERRORS = Counter("mcp_call_errors_total", "MCP 调用失败", ["path"])
MCP_LATENCY = Histogram("mcp_call_duration_seconds", "MCP 调用延迟", ["path"],
                        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5))

# ── 系统 ──
BACKEND_UP = Gauge("backend_up", "后端服务存活状态 (1/0)")
OFFLINE_MODE = Gauge("agent_offline_mode", "离线模式 (1/0)")
REPORT_FILES = Gauge("report_files_active", "当前有效报告文件数")