"""
Prometheus 指标 [v7.1]。

跟踪的指标：
- request_total：已处理的请求总数
- rule_hit_total：L0 规则引擎命中次数
- tool_calls_total：后端 API 工具调用次数
- loop_iterations_total：ReAct 循环迭代次数
- degradation_level：当前降级级别（gauge）
- token_usage_total：预估 token 消耗量
- narrator_validation_failures：Narrator 校验失败次数
- request_duration_seconds：请求处理耗时

挂载于 server.py 的 /metrics 端点。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram

    class Metrics:
        """Prometheus 指标收集器。"""

        def __init__(self):
            self.request_total = Counter(
                "fiber_agent_request_total",
                "Total requests processed",
                ["processing_path"],
            )
            self.rule_hit_total = Counter(
                "fiber_agent_rule_hit_total",
                "L0 rule engine hits",
                ["rule_id"],
            )
            self.tool_calls_total = Counter(
                "fiber_agent_tool_calls_total",
                "Backend API tool calls",
                ["tool_name", "status"],
            )
            self.loop_iterations_total = Counter(
                "fiber_agent_loop_iterations_total",
                "ReAct loop iterations",
            )
            self.degradation_level = Gauge(
                "fiber_agent_degradation_level",
                "Current degradation level (0-4)",
            )
            self.token_usage_total = Counter(
                "fiber_agent_token_usage_total",
                "Estimated token consumption",
                ["tier"],
            )
            self.narrator_validation_failures = Counter(
                "fiber_agent_narrator_validation_failures_total",
                "Narrator validator failures",
            )
            self.request_duration = Histogram(
                "fiber_agent_request_duration_seconds",
                "Request processing time",
                ["processing_path"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            )

        def record_request(self, path: str) -> None:
            self.request_total.labels(processing_path=path).inc()

        def record_rule_hit(self, rule_id: str) -> None:
            self.rule_hit_total.labels(rule_id=rule_id).inc()

        def record_tool_call(self, tool_name: str, success: bool) -> None:
            self.tool_calls_total.labels(tool_name=tool_name, status="success" if success else "error").inc()

        def record_loop_iteration(self) -> None:
            self.loop_iterations_total.inc()

        def set_degradation_level(self, level: int) -> None:
            self.degradation_level.set(level)

        def record_tokens(self, tier: str, count: int) -> None:
            self.token_usage_total.labels(tier=tier).inc(count)

        def record_narrator_failure(self) -> None:
            self.narrator_validation_failures.inc()

        def observe_duration(self, path: str, seconds: float) -> None:
            self.request_duration.labels(processing_path=path).observe(seconds)

    metrics = Metrics()

except ImportError:
    logger.warning("[Metrics] prometheus_client not installed, metrics disabled")

    class _NoopMetrics:
        """当 prometheus_client 不可用时的空操作指标。"""

        def record_request(self, *a, **kw):
            pass

        def record_rule_hit(self, *a, **kw):
            pass

        def record_tool_call(self, *a, **kw):
            pass

        def record_loop_iteration(self, *a, **kw):
            pass

        def set_degradation_level(self, *a, **kw):
            pass

        def record_tokens(self, *a, **kw):
            pass

        def record_narrator_failure(self, *a, **kw):
            pass

        def observe_duration(self, *a, **kw):
            pass

    metrics = _NoopMetrics()
