"""
v8 指标聚合层 — Prometheus 风格计数器.

无外部依赖（不引入 prometheus_client），纯内存实现。
暴露 get_metrics() 供 /metrics 端点或日志输出。

指标列表：
- v8_agent_latency_ms{layer, mode}     — Agent 执行延迟
- v8_agent_calls_total{layer, status}   — Agent 调用计数（success/failure）
- v8_llm_calls_total{agent}             — LLM 调用计数
- v8_loop_rounds                        — 循环轮次分布
- v8_collection_mode_total{mode}        — 采集模式（deterministic/react）
- v8_circuit_breaker_state              — 熔断器状态
- v8_security_blocked_total             — 安全拦截计数
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class MetricsCollector:
    """线程安全的内存指标收集器."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}
        self._start_time = time.time()

    def inc_counter(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0):
        """递增计数器."""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None):
        """记录直方图观测值."""
        key = self._make_key(name, labels)
        with self._lock:
            self._histograms[key].append(value)
            # 保留最近 1000 个观测值
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-500:]

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        """设置仪表盘值."""
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def get_metrics(self) -> dict[str, Any]:
        """获取所有指标快照."""
        with self._lock:
            return {
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: {
                        "count": len(v),
                        "sum": round(sum(v), 2),
                        "avg": round(sum(v) / len(v), 2) if v else 0,
                        "p95": round(sorted(v)[int(len(v) * 0.95)] if v else 0, 2),
                    }
                    for k, v in self._histograms.items()
                },
            }

    def format_prometheus(self) -> str:
        """格式化为 Prometheus 文本格式."""
        lines = []
        with self._lock:
            for key, val in sorted(self._counters.items()):
                lines.append(f"{key} {val}")
            for key, val in sorted(self._gauges.items()):
                lines.append(f"{key} {val}")
            for key, values in sorted(self._histograms.items()):
                if values:
                    lines.append(f"{key}_count {len(values)}")
                    lines.append(f"{key}_sum {sum(values):.2f}")
        return "\n".join(lines)

    @staticmethod
    def _make_key(name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# =============================================================================
# 全局单例
# =============================================================================

_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """获取全局指标收集器."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def reset_metrics() -> None:
    """重置（测试用）."""
    global _metrics
    _metrics = None


# =============================================================================
# 便捷埋点函数
# =============================================================================


def record_agent_execution(
    layer: str, mode: str, latency_ms: float, success: bool
):
    """记录 Agent 执行指标."""
    m = get_metrics()
    m.observe_histogram(
        "v8_agent_latency_ms", latency_ms, {"layer": layer, "mode": mode}
    )
    m.inc_counter(
        "v8_agent_calls_total",
        {"layer": layer, "status": "success" if success else "failure"},
    )


def record_llm_call(agent: str):
    """记录 LLM 调用."""
    get_metrics().inc_counter("v8_llm_calls_total", {"agent": agent})


def record_collection_mode(mode: str):
    """记录采集模式."""
    get_metrics().inc_counter("v8_collection_mode_total", {"mode": mode})


def record_loop_rounds(rounds: int):
    """记录循环轮次."""
    get_metrics().observe_histogram("v8_loop_rounds", float(rounds))


def record_security_block():
    """记录安全拦截."""
    get_metrics().inc_counter("v8_security_blocked_total")
