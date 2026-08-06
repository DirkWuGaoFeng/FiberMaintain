"""
Performance benchmark tests [v7.2].

Validates:
- Rule engine matching latency (< 10ms)
- Fast path end-to-end latency with mock backend (< 500ms)
- RequestTracer overhead (< 5ms)
- Concurrent tracer isolation (10 parallel tracers)
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from src.nodes.rule_engine import RuleEngine
from src.observability.request_tracer import RequestTracer, get_current_tracer


class TestRuleEngineLatency:
    """Rule engine matching must be < 10ms (pure regex, zero LLM)."""

    def test_rule_engine_latency_single(self):
        """Single rule match < 10ms."""
        start = time.perf_counter()
        result = RuleEngine.match("查询光纤1的衰耗")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        assert elapsed_ms < 10, f"Rule match took {elapsed_ms:.2f}ms (limit: 10ms)"

    def test_rule_engine_latency_miss(self):
        """Rule miss (all patterns checked) < 10ms."""
        start = time.perf_counter()
        result = RuleEngine.match("这是一个完全无关的输入，不会匹配任何规则")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is None
        assert elapsed_ms < 10, f"Rule miss took {elapsed_ms:.2f}ms (limit: 10ms)"

    def test_rule_engine_latency_batch(self):
        """100 consecutive matches < 100ms total (< 1ms avg)."""
        queries = [
            "查询光纤1的衰耗",
            "连纤3颜色",
            "目前断纤有哪些",
            "分析连纤2中断的原因",
            "光纤5的性能",
            "有哪些红色光纤",
            "光纤总数有多少",
            "什么是OTDR",
            "生成本周报告",
            "2号盘3号口的告警",
        ]

        start = time.perf_counter()
        for _ in range(10):  # 10 iterations × 10 queries = 100 matches
            for q in queries:
                RuleEngine.match(q)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"100 matches took {elapsed_ms:.2f}ms (limit: 100ms)"

    def test_rule_engine_v72_rules_latency(self):
        """New v7.2 rules (R101-R105) match within latency budget."""
        v72_queries = [
            "分析连纤1中断的原因",
            "连纤3颜色",
            "目前断纤有哪些",
            "光纤3中断的原因",
            "光纤5衰耗",
        ]

        for q in v72_queries:
            start = time.perf_counter()
            result = RuleEngine.match(q)
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert result is not None, f"No match for: {q}"
            assert elapsed_ms < 10, f"'{q}' took {elapsed_ms:.2f}ms"


class TestFastPathLatency:
    """Fast path executor end-to-end with mock backend < 500ms."""

    async def test_fast_path_latency(self, mock_backend):
        """Fast path (rule → API → template) completes < 500ms."""
        from src.nodes.fast_path_executor import fast_path_executor_node

        state = {
            "rule_match": {
                "intent": "spanloss_query",
                "params": {"fiber_id": 1},
                "template_id": "T_SPANLOSS",
                "fast_path_eligible": True,
            },
            "trace_id": "perf-test-001",
            "user_input": "查询光纤1的衰耗",
        }

        start = time.perf_counter()
        result = await fast_path_executor_node(state)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.get("final_output") is not None
        assert result.get("processing_path") == "fast"
        assert elapsed_ms < 500, f"Fast path took {elapsed_ms:.2f}ms (limit: 500ms)"

    async def test_fast_path_connection_query(self, mock_backend):
        """Connection query fast path < 500ms."""
        from src.nodes.fast_path_executor import fast_path_executor_node

        state = {
            "rule_match": {
                "intent": "connection_query",
                "params": {"fiber_id": 3},
                "template_id": "T_CONNECTION",
                "fast_path_eligible": True,
            },
            "trace_id": "perf-test-002",
            "user_input": "连纤3",
        }

        start = time.perf_counter()
        result = await fast_path_executor_node(state)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.get("final_output") is not None
        assert elapsed_ms < 500, f"Connection query took {elapsed_ms:.2f}ms"


class TestTracerOverhead:
    """RequestTracer must add minimal overhead (< 5ms)."""

    def test_tracer_overhead(self, tmp_path):
        """Creating tracer + span + finish adds < 5ms overhead."""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            # Measure baseline (no tracer)
            start = time.perf_counter()
            for _ in range(100):
                _ = {"key": "value"}  # Trivial work
            baseline_ms = (time.perf_counter() - start) * 1000

            # Measure with tracer
            start = time.perf_counter()
            for _ in range(100):
                tracer = RequestTracer(user_input="overhead test")
                with tracer.span("node"):
                    _ = {"key": "value"}
                tracer.finish()
            tracer_ms = (time.perf_counter() - start) * 1000

            # Per-iteration overhead
            overhead_per_iter = (tracer_ms - baseline_ms) / 100
            assert overhead_per_iter < 5, (
                f"Tracer overhead {overhead_per_iter:.2f}ms/iter (limit: 5ms)"
            )

    def test_tracer_span_creation_speed(self):
        """Span creation itself is fast (< 1ms per span)."""
        tracer = RequestTracer(user_input="speed test")

        start = time.perf_counter()
        for i in range(50):
            with tracer.span(f"node_{i}"):
                pass
        elapsed_ms = (time.perf_counter() - start) * 1000

        per_span = elapsed_ms / 50
        assert per_span < 1, f"Span creation {per_span:.3f}ms (limit: 1ms)"
        tracer._finished = True  # Skip finish to avoid file I/O


class TestConcurrentTracers:
    """Multiple concurrent tracers must not interfere."""

    async def test_concurrent_tracers(self, tmp_path):
        """10 concurrent tracers produce correct independent results."""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            results = []

            async def run_tracer(idx: int):
                tracer = RequestTracer(
                    user_input=f"concurrent query {idx}",
                    trace_id=f"conc-{idx:03d}",
                )
                with tracer.span(f"node_{idx}") as span:
                    await asyncio.sleep(0.01)  # Simulate work
                    span.set_output(f"result_{idx}")
                summary = tracer.finish(processing_path="fast")
                return summary

            # Run 10 tracers concurrently
            tasks = [run_tracer(i) for i in range(10)]
            results = await asyncio.gather(*tasks)

            # Verify all completed correctly
            assert len(results) == 10
            for i, summary in enumerate(results):
                assert summary["trace_id"] == f"conc-{i:03d}"
                assert summary["user_input"] == f"concurrent query {i}"
                assert summary["status"] == "SUCCESS"
                assert summary["span_count"] == 1

    async def test_concurrent_tracers_no_cross_contamination(self, tmp_path):
        """Spans from one tracer don't leak into another."""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            tracer_a = RequestTracer(user_input="A", trace_id="iso-a")
            tracer_b = RequestTracer(user_input="B", trace_id="iso-b")

            # tracer_b is now the "current" one
            assert get_current_tracer() is tracer_b

            # Add spans to tracer_a explicitly
            with tracer_a.span("span_a"):
                pass

            # Add spans to tracer_b
            with tracer_b.span("span_b"):
                pass

            # Verify isolation
            assert len(tracer_a.spans) == 1
            assert tracer_a.spans[0].node_name == "span_a"
            assert len(tracer_b.spans) == 1
            assert tracer_b.spans[0].node_name == "span_b"

            tracer_a.finish()
            tracer_b.finish()
