"""
每请求 Token 成本追踪。

记录每次 LLM 调用的 token 消耗和延迟，
提供请求级和日级汇总，供前端 Observability 展示。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CallRecord:
    """单次调用记录。"""

    model: str
    tokens: int
    latency_ms: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class CostTracker:
    """Token 成本追踪器（内存，按日重置）。"""

    def __init__(self):
        self._by_trace: dict[str, list[CallRecord]] = defaultdict(list)
        self._daily: dict[str, list[CallRecord]] = defaultdict(list)

    def record(self, trace_id: str, model: str, tokens: int, latency_ms: int) -> None:
        """记录一次 LLM 调用的成本。"""
        rec = CallRecord(model=model, tokens=tokens, latency_ms=latency_ms)
        self._by_trace[trace_id].append(rec)
        self._daily[date.today().isoformat()].append(rec)

    def get_request_summary(self, trace_id: str) -> dict:
        """获取某请求的成本汇总。"""
        records = self._by_trace.get(trace_id, [])
        return {
            "trace_id": trace_id,
            "total_tokens": sum(r.tokens for r in records),
            "total_latency_ms": sum(r.latency_ms for r in records),
            "call_count": len(records),
            "by_model": self._group_by_model(records),
        }

    def get_daily_summary(self, target_date: Optional[str] = None) -> dict:
        """获取某日的成本汇总。"""
        key = target_date or date.today().isoformat()
        records = self._daily.get(key, [])
        return {
            "date": key,
            "total_tokens": sum(r.tokens for r in records),
            "total_latency_ms": sum(r.latency_ms for r in records),
            "call_count": len(records),
            "by_model": self._group_by_model(records),
        }

    @staticmethod
    def _group_by_model(records: list[CallRecord]) -> dict:
        grouped: dict[str, int] = defaultdict(int)
        for r in records:
            grouped[r.model] += r.tokens
        return dict(grouped)


# 全局单例
_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """获取全局 CostTracker 单例。"""
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
