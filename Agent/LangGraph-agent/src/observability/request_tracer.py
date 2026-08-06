"""
Structured Request Tracer [v7.2-Enhanced].

Full-chain tracing system covering:
- Frontend request reception (via SSE endpoint)
- LangGraph workflow node execution (per-node timing)
- Tool function calls (per-tool timing + params + result)
- RAG retrieval process
- Backend HTTP API calls (already traced via _http_client)
- LLM inference calls (model, tokens, latency)
- Final output delivery

Features:
- Unique trace_id per request (UUID4 short format)
- Span-based timing for each execution phase
- Nested spans for sub-operations (e.g., tool calls within data_collector)
- File output to data/traces/{trace_id}.json for offline analysis
- Structured logging output (INFO level)
- Trace query API for frontend diagnostics panel
- Performance bottleneck auto-detection (spans > 5s flagged)

Usage:
    from src.observability.request_tracer import RequestTracer, get_current_trace_id

    tracer = RequestTracer(user_input="查询光纤 3 的跨段衰耗")
    with tracer.span("rule_engine", input_summary="...") as span:
        # ... execution ...
        span.set_output("match=R001")
    tracer.finish()
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Optional

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

# 当前请求的 trace_id（用于跨模块传递）
_current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
# 当前请求的 tracer 实例（用于节点内嵌套 span）
_current_tracer: ContextVar[Optional["RequestTracer"]] = ContextVar("tracer", default=None)

TRACES_DIR = Path(DATA_DIR) / "traces"

# 性能瓶颈阈值（毫秒）— 超过此值的 span 会被标记
SLOW_SPAN_THRESHOLD_MS = 5000
# 最近 trace 索引（内存中保留最近 100 条摘要，供 API 查询）
_recent_traces: deque[dict] = deque(maxlen=100)


def get_current_trace_id() -> str:
    """Get the current request's trace_id (for HTTP header injection)."""
    return _current_trace_id.get()


def set_current_trace_id(trace_id: str) -> None:
    """Set the current request's trace_id."""
    _current_trace_id.set(trace_id)


def get_current_tracer() -> Optional["RequestTracer"]:
    """Get the current request's tracer instance (for nested spans in nodes)."""
    return _current_tracer.get()


def get_recent_traces(limit: int = 20) -> list[dict]:
    """Get recent trace summaries for the diagnostics API."""
    return list(_recent_traces)[-limit:]


@dataclass
class TraceSpan:
    """A single execution span within a request trace."""

    span_id: str
    node_name: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    input_summary: str = ""
    output_summary: str = ""
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    children: list["TraceSpan"] = field(default_factory=list)
    is_slow: bool = False  # 标记为性能瓶颈

    def set_output(self, output: str) -> None:
        """Set the output summary for this span."""
        self.output_summary = output[:500]  # Truncate to prevent bloat

    def set_error(self, error: str) -> None:
        """Set error information for this span."""
        self.error = error[:1000]

    def set_metadata(self, key: str, value: Any) -> None:
        """Set additional metadata for this span."""
        self.metadata[key] = value

    def add_child(self, child: "TraceSpan") -> None:
        """Add a child span (e.g., tool call within a node)."""
        self.children.append(child)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "span_id": self.span_id,
            "node_name": self.node_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "error": self.error,
            "metadata": self.metadata,
            "is_slow": self.is_slow,
        }
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result


class RequestTracer:
    """
    Request-level tracer with span-based timing [v7.2-Enhanced].

    Collects all spans for a request and outputs:
    1. Structured log lines (INFO level)
    2. JSON file to data/traces/{trace_id}.json
    3. In-memory index for API query
    4. Performance bottleneck detection

    Supports nested spans for sub-operations (tool calls, LLM calls).
    """

    def __init__(self, user_input: str = "", trace_id: Optional[str] = None):
        """
        Initialize a new request tracer.

        Args:
            user_input: The user's input message (for context)
            trace_id: Optional explicit trace_id (auto-generated if not provided)
        """
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.user_input = user_input[:200]  # Truncate for privacy
        self.start_time = time.time()
        self.spans: list[TraceSpan] = []
        self._span_counter = 0
        self._active_spans: list[TraceSpan] = []  # Stack for nested spans
        self._finished = False

        # Set context variables for cross-module access
        set_current_trace_id(self.trace_id)
        _current_tracer.set(self)

        logger.info(f"[TRACE:{self.trace_id}] ═══ START ═══ input=\"{self.user_input}\"")

    @contextmanager
    def span(self, node_name: str, input_summary: str = "") -> Generator[TraceSpan, None, None]:
        """
        Context manager for timing a span.

        Supports nesting: if called within another span, creates a child span.

        Usage:
            with tracer.span("rule_engine", input_summary="...") as span:
                result = do_work()
                span.set_output(f"match={result}")
        """
        self._span_counter += 1
        span = TraceSpan(
            span_id=f"{self.trace_id}-{self._span_counter:03d}",
            node_name=node_name,
            start_time=time.time(),
            input_summary=input_summary[:300],
        )

        # Handle nesting: if there's an active parent span, add as child
        parent = self._active_spans[-1] if self._active_spans else None
        if parent:
            parent.add_child(span)
        else:
            self.spans.append(span)

        self._active_spans.append(span)

        logger.info(
            f"[TRACE:{self.trace_id}] [{node_name}] ▶ START"
            + (f" input={input_summary[:100]}" if input_summary else "")
        )

        try:
            yield span
        except Exception as e:
            span.set_error(str(e))
            raise
        finally:
            self._active_spans.pop()
            span.end_time = time.time()
            span.duration_ms = round((span.end_time - span.start_time) * 1000, 2)

            # 性能瓶颈检测
            if span.duration_ms > SLOW_SPAN_THRESHOLD_MS:
                span.is_slow = True
                logger.warning(
                    f"[TRACE:{self.trace_id}] [{node_name}] ⚠ SLOW {span.duration_ms}ms "
                    f"(threshold={SLOW_SPAN_THRESHOLD_MS}ms)"
                )

            status = "✗ ERROR" if span.error else ("⚠ SLOW" if span.is_slow else "✓ OK")
            logger.info(
                f"[TRACE:{self.trace_id}] [{node_name}] {status} "
                f"{span.duration_ms}ms"
                + (f" output={span.output_summary[:80]}" if span.output_summary else "")
                + (f" error={span.error[:80]}" if span.error else "")
            )

    def record_llm_call(
        self,
        model: str,
        node_name: str,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Record an LLM inference call as a child span of the current active span."""
        self._span_counter += 1
        span = TraceSpan(
            span_id=f"{self.trace_id}-{self._span_counter:03d}",
            node_name=f"llm:{model}",
            start_time=time.time() - duration_ms / 1000,
            end_time=time.time(),
            duration_ms=round(duration_ms, 2),
            input_summary=f"node={node_name}",
            output_summary=f"tokens_in={input_tokens} tokens_out={output_tokens}",
            error=error if not success else None,
            metadata={
                "type": "llm_call",
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "success": success,
            },
            is_slow=duration_ms > SLOW_SPAN_THRESHOLD_MS,
        )
        # Attach to current active span or top-level
        if self._active_spans:
            self._active_spans[-1].add_child(span)
        else:
            self.spans.append(span)

    def record_tool_call(
        self,
        tool_name: str,
        params: dict | str = "",
        duration_ms: float = 0,
        result_summary: str = "",
        success: bool = True,
        error: str = "",
    ) -> None:
        """Record a tool call as a child span of the current active span."""
        self._span_counter += 1
        params_str = json.dumps(params, ensure_ascii=False)[:200] if isinstance(params, dict) else str(params)[:200]
        span = TraceSpan(
            span_id=f"{self.trace_id}-{self._span_counter:03d}",
            node_name=f"tool:{tool_name}",
            start_time=time.time() - duration_ms / 1000,
            end_time=time.time(),
            duration_ms=round(duration_ms, 2),
            input_summary=params_str,
            output_summary=result_summary[:300],
            error=error if not success else None,
            metadata={"type": "tool_call", "tool": tool_name, "success": success},
            is_slow=duration_ms > SLOW_SPAN_THRESHOLD_MS,
        )
        if self._active_spans:
            self._active_spans[-1].add_child(span)
        else:
            self.spans.append(span)

    def finish(self, processing_path: str = "normal", final_output: str = "") -> dict:
        """
        Finish tracing and write results.

        Args:
            processing_path: The processing path taken (fast/normal/heavy/degraded)
            final_output: The final output text

        Returns:
            Summary dict with trace results
        """
        if self._finished:
            return {}
        self._finished = True

        total_ms = round((time.time() - self.start_time) * 1000, 2)
        has_error = any(s.error for s in self.spans)
        slow_spans = [s for s in self.spans if s.is_slow]
        status = "ERROR" if has_error else ("SLOW" if slow_spans else "SUCCESS")

        # 计算各阶段耗时占比
        phase_breakdown = []
        for s in self.spans:
            if s.duration_ms:
                phase_breakdown.append({
                    "node": s.node_name,
                    "duration_ms": s.duration_ms,
                    "percentage": round(s.duration_ms / total_ms * 100, 1) if total_ms > 0 else 0,
                    "is_slow": s.is_slow,
                })

        summary = {
            "trace_id": self.trace_id,
            "user_input": self.user_input,
            "processing_path": processing_path,
            "total_ms": total_ms,
            "span_count": len(self.spans),
            "status": status,
            "slow_spans": [{"node": s.node_name, "duration_ms": s.duration_ms} for s in slow_spans],
            "phase_breakdown": phase_breakdown,
            "final_output": final_output[:300] if final_output else "",
            "spans": [s.to_dict() for s in self.spans],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        # Log summary with bottleneck highlights
        bottleneck_info = ""
        if slow_spans:
            bottleneck_info = " | BOTTLENECKS: " + ", ".join(
                f"{s.node_name}({s.duration_ms}ms)" for s in slow_spans
            )
        logger.info(
            f"[TRACE:{self.trace_id}] ═══ END ═══ Total={total_ms}ms "
            f"Path={processing_path} Status={status} Spans={len(self.spans)}"
            f"{bottleneck_info}"
        )

        # Write to file
        self._write_trace_file(summary)

        # Add to recent traces index (摘要，不含完整 spans)
        _recent_traces.append({
            "trace_id": self.trace_id,
            "user_input": self.user_input,
            "processing_path": processing_path,
            "total_ms": total_ms,
            "status": status,
            "slow_spans": summary["slow_spans"],
            "timestamp": summary["timestamp"],
        })

        # Clear context
        _current_tracer.set(None)

        return summary

    def _write_trace_file(self, summary: dict) -> None:
        """Write trace to JSON file for offline analysis."""
        try:
            TRACES_DIR.mkdir(parents=True, exist_ok=True)
            trace_file = TRACES_DIR / f"{self.trace_id}.json"
            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
            logger.debug(f"[TRACE:{self.trace_id}] Written to {trace_file}")
        except Exception as e:
            logger.warning(f"[TRACE:{self.trace_id}] Failed to write trace file: {e}")

    def get_summary_line(self) -> str:
        """Get a one-line summary for quick display."""
        total_ms = round((time.time() - self.start_time) * 1000, 2)
        has_error = any(s.error for s in self.spans)
        slow_count = sum(1 for s in self.spans if s.is_slow)
        status = "ERROR" if has_error else (f"SLOW({slow_count})" if slow_count else "OK")
        return (
            f"[TRACE:{self.trace_id}] {total_ms}ms | "
            f"Spans={len(self.spans)} | Status={status}"
        )


# =============================================================================
# Node-level tracing decorator [v7.2]
# =============================================================================

def traced_node(node_name: str):
    """
    Decorator for LangGraph node functions to auto-trace execution.

    Wraps async node functions with timing, input/output capture, and error tracking.
    Integrates with the current RequestTracer if one is active.

    Usage:
        @traced_node("rule_engine")
        async def rule_engine_node(state: MainGraphState) -> dict:
            ...
    """
    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(state: dict) -> dict:
            tracer = get_current_tracer()
            trace_id = state.get("trace_id", "")

            if tracer:
                # Use tracer's span for full integration
                input_summary = state.get("user_input", "")[:100]
                with tracer.span(node_name, input_summary=input_summary) as span:
                    try:
                        result = await func(state)
                        # Capture key output fields
                        output_parts = []
                        if result.get("intent"):
                            output_parts.append(f"intent={result['intent']}")
                        if result.get("processing_path"):
                            output_parts.append(f"path={result['processing_path']}")
                        if result.get("final_output"):
                            output_parts.append(f"output_len={len(result['final_output'])}")
                        if result.get("rule_match"):
                            output_parts.append(f"rule={result['rule_match'].get('intent', '?')}")
                        if result.get("degradation_level"):
                            output_parts.append(f"degrade=L{result['degradation_level']}")
                        span.set_output(", ".join(output_parts) if output_parts else "ok")
                        return result
                    except Exception as e:
                        span.set_error(str(e))
                        raise
            else:
                # Fallback: standalone timing log (no tracer active)
                start = time.time()
                logger.info(f"[TRACE:{trace_id}] [{node_name}] ▶ START")
                try:
                    result = await func(state)
                    elapsed = round((time.time() - start) * 1000, 2)
                    logger.info(f"[TRACE:{trace_id}] [{node_name}] ✓ OK {elapsed}ms")
                    return result
                except Exception as e:
                    elapsed = round((time.time() - start) * 1000, 2)
                    logger.error(f"[TRACE:{trace_id}] [{node_name}] ✗ ERROR {elapsed}ms: {e}")
                    raise

        return wrapper
    return decorator


# =============================================================================
# Convenience function for node-level tracing (backward compatible)
# =============================================================================

def trace_node(node_name: str, state: dict) -> tuple[RequestTracer | None, TraceSpan | None]:
    """
    Helper to get tracer from context and start a span.

    Returns (tracer, span) tuple. If no tracer active, returns (None, None).
    Note: Caller must call span context manager properly. Prefer @traced_node decorator.
    """
    tracer = get_current_tracer()
    if not tracer:
        return None, None
    return tracer, None
