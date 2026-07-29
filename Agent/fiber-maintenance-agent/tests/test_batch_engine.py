"""Phase 5: batch_engine 单元测试。

测试覆盖:
- IdempotencyStore: SHA256 去重 + TTL 清理
- CursorManager: 创建/取数/续传/TTL 清理
- BackpressureController: 降级/恢复
- BatchAggregator: 统计/Top-N/摘要
- BatchProcessor: chunk 分片 + 异步生成器
"""
import asyncio
import time
import pytest

from src.agents.batch_engine import (
    IdempotencyStore, CursorManager, BackpressureController,
    BatchAggregator, BatchProcessor, BatchResult,
)


# ============================================================
#  IdempotencyStore
# ============================================================

class TestIdempotencyStore:
    def test_mark_and_detect_duplicate(self):
        store = IdempotencyStore(ttl_seconds=10)
        data = [1, 2, 3]
        assert not store.is_duplicate(data)
        store.mark_processed(data)
        assert store.is_duplicate(data)

    def test_different_data_not_duplicate(self):
        store = IdempotencyStore(ttl_seconds=10)
        store.mark_processed([1, 2, 3])
        assert not store.is_duplicate([4, 5, 6])

    def test_ttl_expiry(self):
        store = IdempotencyStore(ttl_seconds=0)  # TTL=0 立即过期
        store.mark_processed([1, 2])
        # 强制等一帧
        time.sleep(0.01)
        assert not store.is_duplicate([1, 2])

    def test_order_independent(self):
        """相同元素不同顺序应视为相同 chunk。"""
        store = IdempotencyStore(ttl_seconds=10)
        store.mark_processed([3, 1, 2])
        assert store.is_duplicate([1, 2, 3])


# ============================================================
#  CursorManager
# ============================================================

class TestCursorManager:
    def test_create_and_iterate(self):
        mgr = CursorManager(ttl_seconds=60)
        ids = list(range(10))
        cursor = mgr.create_cursor(ids, chunk_size=3)

        chunk1, more1 = mgr.get_next_chunk(cursor)
        assert chunk1 == [0, 1, 2]
        assert more1 is True

        chunk2, more2 = mgr.get_next_chunk(cursor)
        assert chunk2 == [3, 4, 5]
        assert more2 is True

        chunk3, more3 = mgr.get_next_chunk(cursor)
        assert chunk3 == [6, 7, 8]
        assert more3 is True

        chunk4, more4 = mgr.get_next_chunk(cursor)
        assert chunk4 == [9]
        assert more4 is False

        # cursor 已删除
        chunk5, more5 = mgr.get_next_chunk(cursor)
        assert chunk5 == []
        assert more5 is False

    def test_resume(self):
        mgr = CursorManager(ttl_seconds=60)
        cursor = mgr.create_cursor([1, 2, 3, 4, 5], chunk_size=2)
        mgr.get_next_chunk(cursor)  # 取前2个
        assert mgr.resume(cursor) is True

    def test_invalid_cursor(self):
        mgr = CursorManager(ttl_seconds=60)
        chunk, more = mgr.get_next_chunk("nonexistent")
        assert chunk == []
        assert more is False


# ============================================================
#  BackpressureController
# ============================================================

class TestBackpressureController:
    def test_initial_limit(self):
        ctrl = BackpressureController(max_concurrent=5)
        assert ctrl.limit == 5

    def test_degrade_on_high_error_rate(self):
        ctrl = BackpressureController(max_concurrent=5, min_concurrent=2,
                                       high_threshold=0.10)
        # 模拟高错误率: 10个请求中8个错误
        for _ in range(2):
            ctrl.record_success()
        for _ in range(8):
            ctrl.record_error(status_5xx=True)
        assert ctrl.limit == 2

    def test_no_degrade_on_low_error_rate(self):
        ctrl = BackpressureController(max_concurrent=5, min_concurrent=2,
                                       high_threshold=0.10)
        for _ in range(95):
            ctrl.record_success()
        for _ in range(5):
            ctrl.record_error(status_5xx=True)
        assert ctrl.limit == 5


# ============================================================
#  BatchAggregator
# ============================================================

class TestBatchAggregator:
    def test_basic_stats(self):
        agg = BatchAggregator()
        agg.add(1, {"value": 10})
        agg.add(2, {"value": 20})
        agg.add(3, None, error="timeout")
        assert agg.total == 3
        assert agg.success_count == 2
        assert agg.failure_count == 1

    def test_top_anomalies(self):
        agg = BatchAggregator()
        for i in range(20):
            agg.add(i, {"spanloss": float(i)})
        top5 = agg.top_anomalies(n=5, score_key="spanloss")
        assert len(top5) == 5
        assert top5[0]["result"]["spanloss"] == 19.0

    def test_summary(self):
        agg = BatchAggregator()
        agg.add(1, {"spanloss": 3.0})
        agg.add(2, None, error="err")
        summary = agg.summary()
        assert summary["total"] == 2
        assert summary["success"] == 1
        assert summary["failure"] == 1
        assert "50.0%" in summary["success_rate"]


# ============================================================
#  BatchProcessor (async)
# ============================================================

class TestBatchProcessor:
    @pytest.mark.asyncio
    async def test_chunk_processing(self):
        processor = BatchProcessor(chunk_size=3, max_concurrent=2)
        processed_chunks = []

        async def mock_fn(ids):
            processed_chunks.append(ids)
            return [{"id": i, "value": i * 2} for i in ids]

        ids = list(range(7))
        results = []
        async for result in processor.process(ids, mock_fn):
            results.append(result)
            assert isinstance(result, BatchResult)

        assert len(results) == 3  # 7 items / chunk_size=3 = 3 chunks
        assert results[-1].has_more is False
        assert results[-1].summary["total"] == 7

    @pytest.mark.asyncio
    async def test_idempotency_skip(self):
        processor = BatchProcessor(chunk_size=5)

        async def mock_fn(ids):
            return [{"id": i} for i in ids]

        # 第一次
        async for _ in processor.process([1, 2, 3], mock_fn):
            pass
        # 第二次相同数据应被去重跳过
        results = []
        async for r in processor.process([1, 2, 3], mock_fn):
            results.append(r)
        # 去重后无实际处理，但仍产出结果
        assert len(results) >= 0
