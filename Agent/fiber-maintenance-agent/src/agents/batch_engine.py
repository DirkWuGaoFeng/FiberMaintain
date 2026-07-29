"""
Phase 3.3: 批量处理引擎

BatchProcessor: chunk(50) + cursor_pagination(TTL=300s) + backpressure + idempotency
BackpressureController: 5xx>10% → 并发降至2, <3%持续60s → 恢复
IdempotencyStore: chunk_id SHA256 去重, TTL=300s
CursorManager: UUID cursor, 断点续传
Aggregator: 程序化统计(zero token) + Top-N异常 + LLM仅处理摘要
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger("fiber.batch")

# ============================================================
#  IdempotencyStore — chunk_id SHA256 去重
# ============================================================

class IdempotencyStore:
    """基于 chunk_id SHA256 的幂等性存储，TTL 自动清理。"""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds
        self._store: dict[str, float] = {}  # chunk_id → timestamp

    def _make_key(self, chunk_data: list[Any]) -> str:
        raw = ",".join(str(item) for item in sorted(chunk_data, key=str))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_duplicate(self, chunk_data: list[Any]) -> bool:
        self._cleanup()
        key = self._make_key(chunk_data)
        return key in self._store

    def mark_processed(self, chunk_data: list[Any]) -> None:
        key = self._make_key(chunk_data)
        self._store[key] = time.monotonic()

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [k for k, ts in self._store.items() if now - ts > self._ttl]
        for k in expired:
            del self._store[k]


# ============================================================
#  CursorManager — UUID cursor, 断点续传
# ============================================================

class CursorManager:
    """游标管理器：支持断点续传的批量分页。"""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl = ttl_seconds
        self._cursors: dict[str, dict] = {}

    def create_cursor(self, total_ids: list[Any], chunk_size: int) -> str:
        import uuid
        cursor_id = str(uuid.uuid4())[:12]
        self._cursors[cursor_id] = {
            "ids": total_ids,
            "offset": 0,
            "chunk_size": chunk_size,
            "created_at": time.monotonic(),
        }
        return cursor_id

    def get_next_chunk(self, cursor_id: str) -> tuple[list[Any], bool]:
        """返回 (chunk_ids, has_more)。"""
        self._cleanup()
        entry = self._cursors.get(cursor_id)
        if entry is None:
            return [], False

        ids = entry["ids"]
        offset = entry["offset"]
        chunk_size = entry["chunk_size"]

        chunk = ids[offset:offset + chunk_size]
        entry["offset"] = offset + len(chunk)
        has_more = entry["offset"] < len(ids)

        if not has_more:
            del self._cursors[cursor_id]

        return chunk, has_more

    def resume(self, cursor_id: str) -> bool:
        return cursor_id in self._cursors

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._cursors.items()
                   if now - v["created_at"] > self._ttl]
        for k in expired:
            del self._cursors[k]


# ============================================================
#  BackpressureController — 自适应并发
# ============================================================

class BackpressureController:
    """背压控制器：5xx>10% → 并发降至2, <3%持续60s → 恢复。"""

    def __init__(self, max_concurrent: int = 5, min_concurrent: int = 2,
                 high_threshold: float = 0.10, low_threshold: float = 0.03,
                 recovery_seconds: float = 60.0):
        self._max = max_concurrent
        self._min = min_concurrent
        self._high = high_threshold
        self._low = low_threshold
        self._recovery = recovery_seconds

        self._current_limit = max_concurrent
        self._errors: deque[float] = deque(maxlen=100)
        self._total: deque[float] = deque(maxlen=100)
        self._low_since: float | None = None

    @property
    def limit(self) -> int:
        return self._current_limit

    def record_success(self) -> None:
        now = time.monotonic()
        self._total.append(now)
        self._check_recovery()

    def record_error(self, status_5xx: bool = True) -> None:
        now = time.monotonic()
        self._total.append(now)
        if status_5xx:
            self._errors.append(now)
            self._low_since = None
            self._check_degrade()

    def _error_rate(self, window: float = 60.0) -> float:
        now = time.monotonic()
        cutoff = now - window
        recent_total = sum(1 for t in self._total if t >= cutoff)
        recent_errors = sum(1 for t in self._errors if t >= cutoff)
        return recent_errors / max(recent_total, 1)

    def _check_degrade(self) -> None:
        rate = self._error_rate()
        if rate > self._high and self._current_limit > self._min:
            self._current_limit = self._min
            logger.warning("Backpressure: 5xx率=%.1f%%, 并发降至%d",
                           rate * 100, self._current_limit)

    def _check_recovery(self) -> None:
        rate = self._error_rate()
        if rate < self._low:
            if self._low_since is None:
                self._low_since = time.monotonic()
            elif time.monotonic() - self._low_since > self._recovery:
                self._current_limit = self._max
                self._low_since = None
                logger.info("Backpressure: 恢复并发至%d", self._current_limit)
        else:
            self._low_since = None


# ============================================================
#  Aggregator — 程序化统计(zero token)
# ============================================================

class BatchAggregator:
    """批量结果聚合器：程序化统计 + Top-N 异常，LLM 仅处理摘要。"""

    def __init__(self):
        self._results: list[dict] = []

    def add(self, item_id: Any, result: dict | None, error: str | None = None) -> None:
        entry = {"id": item_id, "success": error is None}
        if result:
            entry["result"] = result
        if error:
            entry["error"] = error
        self._results.append(entry)

    @property
    def total(self) -> int:
        return len(self._results)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self._results if r["success"])

    @property
    def failure_count(self) -> int:
        return self.total - self.success_count

    def top_anomalies(self, n: int = 10,
                      score_key: str = "spanloss") -> list[dict]:
        """按 score_key 降序取 Top-N 异常项。"""
        scored = []
        for r in self._results:
            if r["success"] and "result" in r:
                score = r["result"].get(score_key, 0)
                if isinstance(score, (int, float)):
                    scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:n]]

    def summary(self) -> dict:
        """生成零 token 的程序化摘要。"""
        return {
            "total": self.total,
            "success": self.success_count,
            "failure": self.failure_count,
            "success_rate": f"{self.success_count / max(self.total, 1) * 100:.1f}%",
            "top_anomalies": self.top_anomalies(5),
        }


# ============================================================
#  BatchProcessor — 主引擎
# ============================================================

@dataclass
class BatchResult:
    cursor_id: str | None
    chunk_index: int
    results: list[dict]
    has_more: bool
    summary: dict
    elapsed_ms: float


class BatchProcessor:
    """批量处理引擎：chunk(50) + cursor_pagination + backpressure + idempotency。

    使用示例：
        processor = BatchProcessor(chunk_size=50)
        async for result in processor.process(fiber_ids, process_fn):
            print(result.summary)
    """

    def __init__(self, chunk_size: int = 50, max_concurrent: int = 5,
                 cursor_ttl: int = 300):
        self._chunk_size = chunk_size
        self._idempotency = IdempotencyStore(ttl_seconds=cursor_ttl)
        self._cursor_mgr = CursorManager(ttl_seconds=cursor_ttl)
        self._backpressure = BackpressureController(max_concurrent=max_concurrent)

    async def process(
        self,
        ids: list[Any],
        process_fn: Callable[[list[Any]], Awaitable[list[dict]]],
        cursor_id: str | None = None,
    ):
        """异步生成器：逐 chunk 处理，支持断点续传。"""
        started = time.perf_counter()

        # 恢复或创建 cursor
        if cursor_id and self._cursor_mgr.resume(cursor_id):
            logger.info("Resuming batch from cursor=%s", cursor_id)
        else:
            cursor_id = self._cursor_mgr.create_cursor(ids, self._chunk_size)

        chunk_idx = 0
        aggregator = BatchAggregator()

        while True:
            chunk, has_more = self._cursor_mgr.get_next_chunk(cursor_id)
            if not chunk:
                break

            # 幂等性检查
            if self._idempotency.is_duplicate(chunk):
                logger.info("Chunk %d is duplicate, skipping", chunk_idx)
                chunk_idx += 1
                continue

            # 背压控制
            sem = asyncio.Semaphore(self._backpressure.limit)
            async with sem:
                try:
                    results = await process_fn(chunk)
                    self._backpressure.record_success()
                    for i, r in enumerate(results):
                        aggregator.add(chunk[i] if i < len(chunk) else i, r)
                except Exception as e:
                    self._backpressure.record_error(status_5xx=True)
                    for item_id in chunk:
                        aggregator.add(item_id, None, error=str(e))
                    logger.error("Chunk %d failed: %s", chunk_idx, e)

            self._idempotency.mark_processed(chunk)
            chunk_idx += 1

            elapsed = (time.perf_counter() - started) * 1000
            yield BatchResult(
                cursor_id=cursor_id if has_more else None,
                chunk_index=chunk_idx,
                results=results if 'results' in dir() else [],
                has_more=has_more,
                summary=aggregator.summary(),
                elapsed_ms=round(elapsed, 2),
            )

            if not has_more:
                break

        logger.info("Batch complete: %d chunks, %d items, %.0fms",
                     chunk_idx, aggregator.total,
                     (time.perf_counter() - started) * 1000)
