"""
性能基准测试 [v7.2]。

验证：
- 规则引擎匹配延迟（< 10ms）
- 使用 mock 后端的快速路径端到端延迟（< 500ms）
- RequestTracer 开销（< 5ms）
- 并发 tracer 隔离（10 个并行 tracer）
"""

import asyncio
import time
from unittest.mock import patch

from src.nodes.rule_engine import RuleEngine
from src.observability.request_tracer import RequestTracer, get_current_tracer


class TestRuleEngineLatency:
    """规则引擎匹配必须 < 10ms（纯正则，零 LLM）。"""

    def test_rule_engine_latency_single(self):
        """单条规则匹配 < 10ms。"""
        start = time.perf_counter()
        result = RuleEngine.match("查询光纤1的衰耗")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        assert elapsed_ms < 10, f"Rule match took {elapsed_ms:.2f}ms (limit: 10ms)"

    def test_rule_engine_latency_miss(self):
        """规则未命中（全部模式已检查）< 10ms。"""
        start = time.perf_counter()
        result = RuleEngine.match("这是一个完全无关的输入，不会匹配任何规则")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is None
        assert elapsed_ms < 10, f"Rule miss took {elapsed_ms:.2f}ms (limit: 10ms)"

    def test_rule_engine_latency_batch(self):
        """连续 100 次匹配总耗时 < 100ms（平均 < 1ms）。"""
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
        for _ in range(10):  # 10 次迭代 × 10 条查询 = 100 次匹配
            for q in queries:
                RuleEngine.match(q)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100, f"100 matches took {elapsed_ms:.2f}ms (limit: 100ms)"

    def test_rule_engine_v72_rules_latency(self):
        """新增的 v7.2 规则（R101-R105）在延迟预算内完成匹配。"""
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
    """使用 mock 后端的快速路径执行器端到端耗时 < 500ms。"""

    async def test_fast_path_latency(self, mock_backend):
        """快速路径（规则 → API → 模板）在 < 500ms 内完成。"""
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
        """连纤查询快速路径 < 500ms。"""
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
    """RequestTracer 必须只引入极小的额外开销（< 5ms）。"""

    def test_tracer_overhead(self, tmp_path):
        """创建 tracer + span + finish 增加 < 5ms 开销。"""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            # 测量基线（无 tracer）
            start = time.perf_counter()
            for _ in range(100):
                _ = {"key": "value"}  # 无关紧要的工作
            baseline_ms = (time.perf_counter() - start) * 1000

            # 测量带 tracer 的开销
            start = time.perf_counter()
            for _ in range(100):
                tracer = RequestTracer(user_input="overhead test")
                with tracer.span("node"):
                    _ = {"key": "value"}
                tracer.finish()
            tracer_ms = (time.perf_counter() - start) * 1000

            # 每次迭代的额外开销
            overhead_per_iter = (tracer_ms - baseline_ms) / 100
            assert overhead_per_iter < 5, f"Tracer overhead {overhead_per_iter:.2f}ms/iter (limit: 5ms)"

    def test_tracer_span_creation_speed(self):
        """span 创建本身很快（每个 span < 1ms）。"""
        tracer = RequestTracer(user_input="speed test")

        start = time.perf_counter()
        for i in range(50):
            with tracer.span(f"node_{i}"):
                pass
        elapsed_ms = (time.perf_counter() - start) * 1000

        per_span = elapsed_ms / 50
        assert per_span < 1, f"Span creation {per_span:.3f}ms (limit: 1ms)"
        tracer._finished = True  # 跳过 finish 以避免文件 I/O


class TestConcurrentTracers:
    """多个并发 tracer 不得相互干扰。"""

    async def test_concurrent_tracers(self, tmp_path):
        """10 个并发 tracer 产生正确且相互独立的结果。"""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            results = []

            async def run_tracer(idx: int):
                tracer = RequestTracer(
                    user_input=f"concurrent query {idx}",
                    trace_id=f"conc-{idx:03d}",
                )
                with tracer.span(f"node_{idx}") as span:
                    await asyncio.sleep(0.01)  # 模拟工作
                    span.set_output(f"result_{idx}")
                summary = tracer.finish(processing_path="fast")
                return summary

            # 并发运行 10 个 tracer
            tasks = [run_tracer(i) for i in range(10)]
            results = await asyncio.gather(*tasks)

            # 验证全部正确完成
            assert len(results) == 10
            for i, summary in enumerate(results):
                assert summary["trace_id"] == f"conc-{i:03d}"
                assert summary["user_input"] == f"concurrent query {i}"
                assert summary["status"] == "SUCCESS"
                assert summary["span_count"] == 1

    async def test_concurrent_tracers_no_cross_contamination(self, tmp_path):
        """一个 tracer 的 span 不会泄漏到另一个 tracer。"""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            tracer_a = RequestTracer(user_input="A", trace_id="iso-a")
            tracer_b = RequestTracer(user_input="B", trace_id="iso-b")

            # tracer_b 现在是"当前"tracer
            assert get_current_tracer() is tracer_b

            # 显式向 tracer_a 添加 span
            with tracer_a.span("span_a"):
                pass

            # 向 tracer_b 添加 span
            with tracer_b.span("span_b"):
                pass

            # 验证隔离
            assert len(tracer_a.spans) == 1
            assert tracer_a.spans[0].node_name == "span_a"
            assert len(tracer_b.spans) == 1
            assert tracer_b.spans[0].node_name == "span_b"

            tracer_a.finish()
            tracer_b.finish()
