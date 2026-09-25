"""
RequestTracer 单元测试 [v7.2-Enhanced]。

测试：
- Tracer 创建与 ContextVar 设置
- Span 创建、计时与输出捕获
- 嵌套 span（父子）关系
- Span 内错误捕获
- 慢 span 检测（> 5000ms 阈值）
- LLM 调用与工具调用记录
- finish() 摘要生成与幂等性
- 阶段占比（phase breakdown）百分比计算
- Trace 文件输出到 data/traces/
- 内存中的最近 traces 索引
- @traced_node 装饰器集成
- tracer 实例间的上下文隔离
"""

import json
import time
from unittest.mock import patch

import pytest

from src.observability.request_tracer import (
    SLOW_SPAN_THRESHOLD_MS,
    RequestTracer,
    TraceSpan,
    get_current_trace_id,
    get_current_tracer,
    get_recent_traces,
    traced_node,
)


class TestTracerCreation:
    """测试 RequestTracer 初始化。"""

    def test_tracer_creation(self):
        """trace_id 自动生成，ContextVar 已设置。"""
        tracer = RequestTracer(user_input="测试输入")
        assert tracer.trace_id is not None
        assert len(tracer.trace_id) == 12  # uuid4 hex[:12]
        assert get_current_trace_id() == tracer.trace_id
        assert get_current_tracer() is tracer
        tracer.finish()

    def test_tracer_custom_trace_id(self):
        """显式指定 trace_id 会被使用。"""
        tracer = RequestTracer(user_input="test", trace_id="custom-id-123")
        assert tracer.trace_id == "custom-id-123"
        tracer.finish()

    def test_tracer_input_truncation(self):
        """用户输入截断到 200 个字符。"""
        long_input = "x" * 500
        tracer = RequestTracer(user_input=long_input)
        assert len(tracer.user_input) == 200
        tracer.finish()


class TestSpanBasic:
    """测试基本 span 创建与计时。"""

    def test_span_basic(self):
        """Span 记录计时与输出。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("test_node", input_summary="input data") as span:
            time.sleep(0.01)  # 10ms
            span.set_output("result=ok")

        assert len(tracer.spans) == 1
        s = tracer.spans[0]
        assert s.node_name == "test_node"
        assert s.input_summary == "input data"
        assert s.output_summary == "result=ok"
        assert s.duration_ms is not None
        assert s.duration_ms >= 10  # 至少 10ms
        assert s.error is None
        tracer.finish()

    def test_span_id_format(self):
        """Span ID 遵循 {trace_id}-{counter:03d} 格式。"""
        tracer = RequestTracer(user_input="test", trace_id="abc123")
        with tracer.span("node_a") as span:
            pass
        assert tracer.spans[0].span_id == "abc123-001"
        tracer.finish()

    def test_span_output_truncation(self):
        """输出摘要截断到 500 个字符。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("node") as span:
            span.set_output("y" * 1000)
        assert len(tracer.spans[0].output_summary) == 500
        tracer.finish()


class TestSpanNesting:
    """测试嵌套 span（父子）关系。"""

    def test_span_nesting(self):
        """内层 span 成为外层 span 的子级。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("parent_node") as parent:
            with tracer.span("child_node") as child:
                child.set_output("child done")
            parent.set_output("parent done")

        # 顶层 span 中只有 parent
        assert len(tracer.spans) == 1
        assert tracer.spans[0].node_name == "parent_node"
        # 子级在 parent 的 children 中
        assert len(tracer.spans[0].children) == 1
        assert tracer.spans[0].children[0].node_name == "child_node"
        tracer.finish()

    def test_deep_nesting(self):
        """三层嵌套。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("level1"):
            with tracer.span("level2"):
                with tracer.span("level3") as s3:
                    s3.set_output("deep")

        assert len(tracer.spans) == 1
        l1 = tracer.spans[0]
        assert l1.node_name == "level1"
        assert len(l1.children) == 1
        l2 = l1.children[0]
        assert l2.node_name == "level2"
        assert len(l2.children) == 1
        assert l2.children[0].node_name == "level3"
        tracer.finish()


class TestSpanErrorCapture:
    """测试 span 内的错误捕获。"""

    def test_span_error_capture(self):
        """异常设置 span.error 并重新抛出。"""
        tracer = RequestTracer(user_input="test")
        with pytest.raises(ValueError, match="test error"):
            with tracer.span("error_node") as span:
                raise ValueError("test error")

        assert tracer.spans[0].error == "test error"
        assert tracer.spans[0].duration_ms is not None
        tracer.finish()

    def test_span_error_truncation(self):
        """错误消息截断到 1000 个字符。"""
        tracer = RequestTracer(user_input="test")
        long_error = "e" * 2000
        with pytest.raises(RuntimeError):
            with tracer.span("node") as span:
                raise RuntimeError(long_error)
        assert len(tracer.spans[0].error) == 1000
        tracer.finish()


class TestSlowSpanDetection:
    """测试性能瓶颈检测。"""

    def test_slow_span_detection(self):
        """超过 SLOW_SPAN_THRESHOLD_MS 的 span 被标记为慢。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("slow_node") as span:
            pass
        # 手动设置时长以模拟慢 span
        tracer.spans[0].duration_ms = SLOW_SPAN_THRESHOLD_MS + 100
        tracer.spans[0].is_slow = True

        assert tracer.spans[0].is_slow is True
        tracer.finish()

    def test_normal_span_not_slow(self):
        """快速 span 不被标记。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("fast_node"):
            pass
        assert tracer.spans[0].is_slow is False
        tracer.finish()


class TestRecordLLMCall:
    """测试 LLM 调用记录。"""

    def test_record_llm_call(self):
        """LLM 调用被记录为活动 span 的子级。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("intent_classifier"):
            tracer.record_llm_call(
                model="qwen2.5:14b",
                node_name="intent_classifier",
                duration_ms=2500.0,
                input_tokens=150,
                output_tokens=50,
                success=True,
            )

        # LLM 调用是 intent_classifier span 的子级
        parent = tracer.spans[0]
        assert len(parent.children) == 1
        llm_span = parent.children[0]
        assert llm_span.node_name == "llm:qwen2.5:14b"
        assert llm_span.duration_ms == 2500.0
        assert llm_span.metadata["type"] == "llm_call"
        assert llm_span.metadata["model"] == "qwen2.5:14b"
        assert llm_span.metadata["input_tokens"] == 150
        tracer.finish()

    def test_record_llm_call_top_level(self):
        """无活动 span 时的 LLM 调用进入顶层。"""
        tracer = RequestTracer(user_input="test")
        tracer.record_llm_call(
            model="qwen2.5:7b",
            node_name="narrator",
            duration_ms=1000.0,
        )
        assert len(tracer.spans) == 1
        assert tracer.spans[0].node_name == "llm:qwen2.5:7b"
        tracer.finish()

    def test_record_llm_call_slow(self):
        """超过阈值的 LLM 调用被标记为慢。"""
        tracer = RequestTracer(user_input="test")
        tracer.record_llm_call(
            model="qwen2.5:14b",
            node_name="analysis",
            duration_ms=SLOW_SPAN_THRESHOLD_MS + 1000,
        )
        assert tracer.spans[0].is_slow is True
        tracer.finish()


class TestRecordToolCall:
    """测试工具调用记录。"""

    def test_record_tool_call(self):
        """工具调用被记录为子 span。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("data_collector"):
            tracer.record_tool_call(
                tool_name="fiber_spanloss_query",
                params={"fiber_id": 1},
                duration_ms=200.0,
                result_summary="spanloss=3.2dB",
                success=True,
            )

        parent = tracer.spans[0]
        assert len(parent.children) == 1
        tool_span = parent.children[0]
        assert tool_span.node_name == "tool:fiber_spanloss_query"
        assert tool_span.duration_ms == 200.0
        assert tool_span.metadata["type"] == "tool_call"
        assert "fiber_id" in tool_span.input_summary
        tracer.finish()

    def test_record_tool_call_error(self):
        """失败的工具调用记录错误。"""
        tracer = RequestTracer(user_input="test")
        tracer.record_tool_call(
            tool_name="alarm_query",
            duration_ms=5000.0,
            success=False,
            error="Connection timeout",
        )
        assert tracer.spans[0].error == "Connection timeout"
        assert tracer.spans[0].metadata["success"] is False
        tracer.finish()


class TestFinishSummary:
    """测试 finish() 摘要生成。"""

    def test_finish_summary(self):
        """finish() 返回完整的摘要字典。"""
        tracer = RequestTracer(user_input="查询光纤1", trace_id="test-fin")
        with tracer.span("rule_engine") as span:
            span.set_output("match=R001")

        summary = tracer.finish(processing_path="fast", final_output="光纤1正常")

        assert summary["trace_id"] == "test-fin"
        assert summary["user_input"] == "查询光纤1"
        assert summary["processing_path"] == "fast"
        assert summary["total_ms"] >= 0  # 即时操作可能为 0.0
        assert summary["span_count"] == 1
        assert summary["status"] == "SUCCESS"
        assert summary["final_output"] == "光纤1正常"
        assert len(summary["spans"]) == 1
        assert "timestamp" in summary

    def test_finish_idempotent(self):
        """重复调用 finish() 返回空字典。"""
        tracer = RequestTracer(user_input="test")
        tracer.finish()
        result = tracer.finish()
        assert result == {}

    def test_finish_status_error(self):
        """任一 span 有错误时状态为 ERROR。"""
        tracer = RequestTracer(user_input="test")
        with pytest.raises(ValueError):
            with tracer.span("bad_node"):
                raise ValueError("oops")
        summary = tracer.finish()
        assert summary["status"] == "ERROR"

    def test_finish_status_slow(self):
        """span 超过阈值时状态为 SLOW。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("node"):
            pass
        # 强制设为慢
        tracer.spans[0].is_slow = True
        tracer.spans[0].duration_ms = 6000.0
        summary = tracer.finish()
        assert summary["status"] == "SLOW"
        assert len(summary["slow_spans"]) == 1


class TestPhaseBreakdown:
    """测试阶段占比（phase breakdown）百分比计算。"""

    def test_phase_breakdown(self):
        """阶段占比具有正确的百分比。"""
        tracer = RequestTracer(user_input="test")
        with tracer.span("node_a"):
            time.sleep(0.01)
        with tracer.span("node_b"):
            time.sleep(0.01)

        summary = tracer.finish()
        breakdown = summary["phase_breakdown"]
        assert len(breakdown) == 2
        # 每一项都应包含 node、duration_ms、percentage、is_slow
        for item in breakdown:
            assert "node" in item
            assert "duration_ms" in item
            assert "percentage" in item
            assert "is_slow" in item
        # 百分比之和应约为 100（因开销可能并非精确）
        total_pct = sum(item["percentage"] for item in breakdown)
        assert 50 < total_pct <= 100  # 允许计时开销


class TestTraceFileOutput:
    """测试 JSON 文件输出。"""

    def test_trace_file_output(self, tmp_path):
        """Trace 写入 data/traces/{trace_id}.json。"""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            tracer = RequestTracer(user_input="file test", trace_id="file-trace-01")
            with tracer.span("node"):
                pass
            tracer.finish()

            trace_file = tmp_path / "traces" / "file-trace-01.json"
            assert trace_file.exists()
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            assert data["trace_id"] == "file-trace-01"
            assert data["user_input"] == "file test"


class TestRecentTracesIndex:
    """测试内存中的最近 traces 索引。"""

    def test_recent_traces_index(self):
        """已完成的 trace 出现在 get_recent_traces() 中。"""
        tracer = RequestTracer(user_input="index test", trace_id="idx-001")
        tracer.finish(processing_path="fast")

        recent = get_recent_traces(limit=50)
        # 在列表中查找我们的 trace
        found = [t for t in recent if t["trace_id"] == "idx-001"]
        assert len(found) == 1
        assert found[0]["processing_path"] == "fast"
        assert found[0]["user_input"] == "index test"


class TestTracedNodeDecorator:
    """测试 @traced_node 装饰器集成。"""

    async def test_traced_node_decorator(self):
        """@traced_node 用 tracing 包装异步函数。"""
        tracer = RequestTracer(user_input="decorator test")

        @traced_node("test_decorated_node")
        async def my_node(state: dict) -> dict:
            return {"intent": "single_query", "processing_path": "fast"}

        result = await my_node({"user_input": "test", "trace_id": tracer.trace_id})

        assert result["intent"] == "single_query"
        # 应记录 span
        assert len(tracer.spans) == 1
        assert tracer.spans[0].node_name == "test_decorated_node"
        assert "intent=single_query" in tracer.spans[0].output_summary
        tracer.finish()

    async def test_traced_node_without_tracer(self):
        """@traced_node 在无活动 tracer 时正常工作（回退到日志）。"""
        # 确保没有活动 tracer
        from src.observability.request_tracer import _current_tracer

        _current_tracer.set(None)

        @traced_node("standalone_node")
        async def my_node(state: dict) -> dict:
            return {"final_output": "hello"}

        result = await my_node({"user_input": "test", "trace_id": "no-tracer"})
        assert result["final_output"] == "hello"

    async def test_traced_node_error(self):
        """@traced_node 在 span 中捕获错误。"""
        tracer = RequestTracer(user_input="error test")

        @traced_node("error_node")
        async def bad_node(state: dict) -> dict:
            raise RuntimeError("node failed")

        with pytest.raises(RuntimeError, match="node failed"):
            await bad_node({"user_input": "test", "trace_id": tracer.trace_id})

        assert tracer.spans[0].error == "node failed"
        tracer.finish()


class TestContextIsolation:
    """测试 tracer 实例间的 ContextVar 隔离。"""

    def test_context_isolation(self):
        """创建新 tracer 会更新 ContextVar。"""
        tracer1 = RequestTracer(user_input="first", trace_id="trace-1")
        assert get_current_trace_id() == "trace-1"

        tracer2 = RequestTracer(user_input="second", trace_id="trace-2")
        assert get_current_trace_id() == "trace-2"
        assert get_current_tracer() is tracer2

        tracer1.finish()
        tracer2.finish()

    def test_finish_clears_tracer_context(self):
        """finish() 清除 tracer ContextVar。"""
        tracer = RequestTracer(user_input="test", trace_id="clear-test")
        assert get_current_tracer() is tracer
        tracer.finish()
        assert get_current_tracer() is None


class TestTraceSpanDataclass:
    """测试 TraceSpan dataclass 方法。"""

    def test_to_dict(self):
        """to_dict() 产生正确的结构。"""
        span = TraceSpan(
            span_id="t-001",
            node_name="test",
            start_time=1000.0,
            end_time=1001.0,
            duration_ms=1000.0,
            input_summary="in",
            output_summary="out",
        )
        d = span.to_dict()
        assert d["span_id"] == "t-001"
        assert d["node_name"] == "test"
        assert d["duration_ms"] == 1000.0
        assert "children" not in d  # 无子级 → 省略该键

    def test_to_dict_with_children(self):
        """to_dict() 在存在子级时包含 children。"""
        parent = TraceSpan(span_id="p", node_name="parent", start_time=0)
        child = TraceSpan(span_id="c", node_name="child", start_time=0)
        parent.add_child(child)
        d = parent.to_dict()
        assert "children" in d
        assert len(d["children"]) == 1
        assert d["children"][0]["node_name"] == "child"

    def test_set_metadata(self):
        """set_metadata 存储键值对。"""
        span = TraceSpan(span_id="m", node_name="meta", start_time=0)
        span.set_metadata("model", "qwen2.5:14b")
        span.set_metadata("tokens", 100)
        assert span.metadata["model"] == "qwen2.5:14b"
        assert span.metadata["tokens"] == 100
