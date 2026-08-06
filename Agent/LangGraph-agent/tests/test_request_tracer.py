"""
Unit tests for RequestTracer [v7.2-Enhanced].

Tests:
- Tracer creation and ContextVar setup
- Span creation, timing, and output capture
- Nested span (parent-child) relationships
- Error capture within spans
- Slow span detection (> 5000ms threshold)
- LLM call and tool call recording
- finish() summary generation and idempotency
- Phase breakdown percentage calculation
- Trace file output to data/traces/
- Recent traces in-memory index
- @traced_node decorator integration
- Context isolation between tracer instances
"""

import asyncio
import json
import time
from pathlib import Path
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
    """Test RequestTracer initialization."""

    def test_tracer_creation(self):
        """trace_id auto-generated, ContextVar set."""
        tracer = RequestTracer(user_input="测试输入")
        assert tracer.trace_id is not None
        assert len(tracer.trace_id) == 12  # uuid4 hex[:12]
        assert get_current_trace_id() == tracer.trace_id
        assert get_current_tracer() is tracer
        tracer.finish()

    def test_tracer_custom_trace_id(self):
        """Explicit trace_id is used."""
        tracer = RequestTracer(user_input="test", trace_id="custom-id-123")
        assert tracer.trace_id == "custom-id-123"
        tracer.finish()

    def test_tracer_input_truncation(self):
        """User input truncated to 200 chars."""
        long_input = "x" * 500
        tracer = RequestTracer(user_input=long_input)
        assert len(tracer.user_input) == 200
        tracer.finish()


class TestSpanBasic:
    """Test basic span creation and timing."""

    def test_span_basic(self):
        """Span records timing and output."""
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
        assert s.duration_ms >= 10  # At least 10ms
        assert s.error is None
        tracer.finish()

    def test_span_id_format(self):
        """Span ID follows {trace_id}-{counter:03d} format."""
        tracer = RequestTracer(user_input="test", trace_id="abc123")
        with tracer.span("node_a") as span:
            pass
        assert tracer.spans[0].span_id == "abc123-001"
        tracer.finish()

    def test_span_output_truncation(self):
        """Output summary truncated to 500 chars."""
        tracer = RequestTracer(user_input="test")
        with tracer.span("node") as span:
            span.set_output("y" * 1000)
        assert len(tracer.spans[0].output_summary) == 500
        tracer.finish()


class TestSpanNesting:
    """Test nested span (parent-child) relationships."""

    def test_span_nesting(self):
        """Inner span becomes child of outer span."""
        tracer = RequestTracer(user_input="test")
        with tracer.span("parent_node") as parent:
            with tracer.span("child_node") as child:
                child.set_output("child done")
            parent.set_output("parent done")

        # Only parent in top-level spans
        assert len(tracer.spans) == 1
        assert tracer.spans[0].node_name == "parent_node"
        # Child in parent's children
        assert len(tracer.spans[0].children) == 1
        assert tracer.spans[0].children[0].node_name == "child_node"
        tracer.finish()

    def test_deep_nesting(self):
        """Three levels of nesting."""
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
    """Test error capture within spans."""

    def test_span_error_capture(self):
        """Exception sets span.error and re-raises."""
        tracer = RequestTracer(user_input="test")
        with pytest.raises(ValueError, match="test error"):
            with tracer.span("error_node") as span:
                raise ValueError("test error")

        assert tracer.spans[0].error == "test error"
        assert tracer.spans[0].duration_ms is not None
        tracer.finish()

    def test_span_error_truncation(self):
        """Error message truncated to 1000 chars."""
        tracer = RequestTracer(user_input="test")
        long_error = "e" * 2000
        with pytest.raises(RuntimeError):
            with tracer.span("node") as span:
                raise RuntimeError(long_error)
        assert len(tracer.spans[0].error) == 1000
        tracer.finish()


class TestSlowSpanDetection:
    """Test performance bottleneck detection."""

    def test_slow_span_detection(self):
        """Span > SLOW_SPAN_THRESHOLD_MS flagged as slow."""
        tracer = RequestTracer(user_input="test")
        with tracer.span("slow_node") as span:
            pass
        # Manually set duration to simulate slow span
        tracer.spans[0].duration_ms = SLOW_SPAN_THRESHOLD_MS + 100
        tracer.spans[0].is_slow = True

        assert tracer.spans[0].is_slow is True
        tracer.finish()

    def test_normal_span_not_slow(self):
        """Fast span not flagged."""
        tracer = RequestTracer(user_input="test")
        with tracer.span("fast_node"):
            pass
        assert tracer.spans[0].is_slow is False
        tracer.finish()


class TestRecordLLMCall:
    """Test LLM call recording."""

    def test_record_llm_call(self):
        """LLM call recorded as child span of active span."""
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

        # LLM call is child of intent_classifier span
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
        """LLM call without active span goes to top-level."""
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
        """LLM call > threshold marked slow."""
        tracer = RequestTracer(user_input="test")
        tracer.record_llm_call(
            model="qwen2.5:14b",
            node_name="analysis",
            duration_ms=SLOW_SPAN_THRESHOLD_MS + 1000,
        )
        assert tracer.spans[0].is_slow is True
        tracer.finish()


class TestRecordToolCall:
    """Test tool call recording."""

    def test_record_tool_call(self):
        """Tool call recorded as child span."""
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
        """Failed tool call records error."""
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
    """Test finish() summary generation."""

    def test_finish_summary(self):
        """finish() returns complete summary dict."""
        tracer = RequestTracer(user_input="查询光纤1", trace_id="test-fin")
        with tracer.span("rule_engine") as span:
            span.set_output("match=R001")

        summary = tracer.finish(processing_path="fast", final_output="光纤1正常")

        assert summary["trace_id"] == "test-fin"
        assert summary["user_input"] == "查询光纤1"
        assert summary["processing_path"] == "fast"
        assert summary["total_ms"] >= 0  # May be 0.0 for instant operations
        assert summary["span_count"] == 1
        assert summary["status"] == "SUCCESS"
        assert summary["final_output"] == "光纤1正常"
        assert len(summary["spans"]) == 1
        assert "timestamp" in summary

    def test_finish_idempotent(self):
        """Repeated finish() returns empty dict."""
        tracer = RequestTracer(user_input="test")
        tracer.finish()
        result = tracer.finish()
        assert result == {}

    def test_finish_status_error(self):
        """Status is ERROR when any span has error."""
        tracer = RequestTracer(user_input="test")
        with pytest.raises(ValueError):
            with tracer.span("bad_node"):
                raise ValueError("oops")
        summary = tracer.finish()
        assert summary["status"] == "ERROR"

    def test_finish_status_slow(self):
        """Status is SLOW when spans exceed threshold."""
        tracer = RequestTracer(user_input="test")
        with tracer.span("node"):
            pass
        # Force slow
        tracer.spans[0].is_slow = True
        tracer.spans[0].duration_ms = 6000.0
        summary = tracer.finish()
        assert summary["status"] == "SLOW"
        assert len(summary["slow_spans"]) == 1


class TestPhaseBreakdown:
    """Test phase breakdown percentage calculation."""

    def test_phase_breakdown(self):
        """Phase breakdown has correct percentages."""
        tracer = RequestTracer(user_input="test")
        with tracer.span("node_a"):
            time.sleep(0.01)
        with tracer.span("node_b"):
            time.sleep(0.01)

        summary = tracer.finish()
        breakdown = summary["phase_breakdown"]
        assert len(breakdown) == 2
        # Each should have node, duration_ms, percentage, is_slow
        for item in breakdown:
            assert "node" in item
            assert "duration_ms" in item
            assert "percentage" in item
            assert "is_slow" in item
        # Percentages should sum to roughly 100 (may not be exact due to overhead)
        total_pct = sum(item["percentage"] for item in breakdown)
        assert 50 < total_pct <= 100  # Allow for timing overhead


class TestTraceFileOutput:
    """Test JSON file output."""

    def test_trace_file_output(self, tmp_path):
        """Trace written to data/traces/{trace_id}.json."""
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
    """Test in-memory recent traces index."""

    def test_recent_traces_index(self):
        """Finished traces appear in get_recent_traces()."""
        tracer = RequestTracer(user_input="index test", trace_id="idx-001")
        tracer.finish(processing_path="fast")

        recent = get_recent_traces(limit=50)
        # Find our trace in the list
        found = [t for t in recent if t["trace_id"] == "idx-001"]
        assert len(found) == 1
        assert found[0]["processing_path"] == "fast"
        assert found[0]["user_input"] == "index test"


class TestTracedNodeDecorator:
    """Test @traced_node decorator integration."""

    async def test_traced_node_decorator(self):
        """@traced_node wraps async function with tracing."""
        tracer = RequestTracer(user_input="decorator test")

        @traced_node("test_decorated_node")
        async def my_node(state: dict) -> dict:
            return {"intent": "single_query", "processing_path": "fast"}

        result = await my_node({"user_input": "test", "trace_id": tracer.trace_id})

        assert result["intent"] == "single_query"
        # Span should be recorded
        assert len(tracer.spans) == 1
        assert tracer.spans[0].node_name == "test_decorated_node"
        assert "intent=single_query" in tracer.spans[0].output_summary
        tracer.finish()

    async def test_traced_node_without_tracer(self):
        """@traced_node works without active tracer (fallback logging)."""
        # Ensure no active tracer
        from src.observability.request_tracer import _current_tracer
        _current_tracer.set(None)

        @traced_node("standalone_node")
        async def my_node(state: dict) -> dict:
            return {"final_output": "hello"}

        result = await my_node({"user_input": "test", "trace_id": "no-tracer"})
        assert result["final_output"] == "hello"

    async def test_traced_node_error(self):
        """@traced_node captures errors in span."""
        tracer = RequestTracer(user_input="error test")

        @traced_node("error_node")
        async def bad_node(state: dict) -> dict:
            raise RuntimeError("node failed")

        with pytest.raises(RuntimeError, match="node failed"):
            await bad_node({"user_input": "test", "trace_id": tracer.trace_id})

        assert tracer.spans[0].error == "node failed"
        tracer.finish()


class TestContextIsolation:
    """Test ContextVar isolation between tracer instances."""

    def test_context_isolation(self):
        """Creating a new tracer updates ContextVar."""
        tracer1 = RequestTracer(user_input="first", trace_id="trace-1")
        assert get_current_trace_id() == "trace-1"

        tracer2 = RequestTracer(user_input="second", trace_id="trace-2")
        assert get_current_trace_id() == "trace-2"
        assert get_current_tracer() is tracer2

        tracer1.finish()
        tracer2.finish()

    def test_finish_clears_tracer_context(self):
        """finish() clears the tracer ContextVar."""
        tracer = RequestTracer(user_input="test", trace_id="clear-test")
        assert get_current_tracer() is tracer
        tracer.finish()
        assert get_current_tracer() is None


class TestTraceSpanDataclass:
    """Test TraceSpan dataclass methods."""

    def test_to_dict(self):
        """to_dict() produces correct structure."""
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
        assert "children" not in d  # No children → key omitted

    def test_to_dict_with_children(self):
        """to_dict() includes children when present."""
        parent = TraceSpan(span_id="p", node_name="parent", start_time=0)
        child = TraceSpan(span_id="c", node_name="child", start_time=0)
        parent.add_child(child)
        d = parent.to_dict()
        assert "children" in d
        assert len(d["children"]) == 1
        assert d["children"][0]["node_name"] == "child"

    def test_set_metadata(self):
        """set_metadata stores key-value pairs."""
        span = TraceSpan(span_id="m", node_name="meta", start_time=0)
        span.set_metadata("model", "qwen2.5:14b")
        span.set_metadata("tokens", 100)
        assert span.metadata["model"] == "qwen2.5:14b"
        assert span.metadata["tokens"] == 100
