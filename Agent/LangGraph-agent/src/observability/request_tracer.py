"""
结构化请求追踪器 [v7.2-Enhanced]。

覆盖全链路的追踪系统：
- 前端请求接收（通过 SSE 端点）
- LangGraph 工作流节点执行（逐节点计时）
- 工具函数调用（逐工具计时 + 参数 + 结果）
- RAG 检索过程
- 后端 HTTP API 调用（已通过 _http_client 追踪）
- LLM 推理调用（模型、tokens、延迟）
- 最终输出交付

特性：
- 每次请求唯一 trace_id（UUID4 短格式）
- 基于 span 的各个执行阶段计时
- 子操作的嵌套 spans（例如 data_collector 内的工具调用）
- 文件输出到 data/traces/{trace_id}.json，供离线分析
- 结构化日志输出（INFO 级别）
- 供前端诊断面板使用的 trace 查询 API
- 性能瓶颈自动检测（超过 5s 的 span 会被标记）

用法：
    from src.observability.request_tracer import RequestTracer, get_current_trace_id

    tracer = RequestTracer(user_input="查询光纤 3 的跨段衰耗")
    with tracer.span("rule_engine", input_summary="...") as span:
        # ... 执行逻辑 ...
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
    """获取当前请求的 trace_id（用于 HTTP 请求头注入）。"""
    return _current_trace_id.get()


def set_current_trace_id(trace_id: str) -> None:
    """设置当前请求的 trace_id。"""
    _current_trace_id.set(trace_id)


def get_current_tracer() -> Optional["RequestTracer"]:
    """获取当前请求的 tracer 实例（用于节点内嵌套 span）。"""
    return _current_tracer.get()


def get_recent_traces(limit: int = 20) -> list[dict]:
    """获取最近的 trace 摘要，供诊断 API 使用。"""
    return list(_recent_traces)[-limit:]


@dataclass
class TraceSpan:
    """请求 trace 中的单个执行 span。"""

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
        """设置该 span 的输出摘要。"""
        self.output_summary = output[:500]  # 截断以防止内容膨胀

    def set_error(self, error: str) -> None:
        """设置该 span 的错误信息。"""
        self.error = error[:1000]

    def set_metadata(self, key: str, value: Any) -> None:
        """为该 span 设置附加元数据。"""
        self.metadata[key] = value

    def add_child(self, child: "TraceSpan") -> None:
        """添加子 span（例如节点内的工具调用）。"""
        self.children.append(child)

    def to_dict(self) -> dict:
        """转换为字典以便进行 JSON 序列化。"""
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
    基于 span 计时的请求级追踪器 [v7.2-Enhanced]。

    收集一个请求的所有 span，并输出：
    1. 结构化日志行（INFO 级别）
    2. 写入 data/traces/{trace_id}.json 的 JSON 文件
    3. 供 API 查询的内存索引
    4. 性能瓶颈检测

    支持子操作（工具调用、LLM 调用）的嵌套 spans。
    """

    def __init__(self, user_input: str = "", trace_id: Optional[str] = None):
        """
        初始化一个新的请求追踪器。

        Args:
            user_input: 用户的输入消息（用于上下文）
            trace_id: 可选的显式 trace_id（未提供时自动生成）
        """
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.user_input = user_input[:200]  # 出于隐私考虑进行截断
        self.start_time = time.time()
        self.spans: list[TraceSpan] = []
        self._span_counter = 0
        self._active_spans: list[TraceSpan] = []  # 用于嵌套 span 的栈
        self._finished = False

        # 设置上下文变量以支持跨模块访问
        set_current_trace_id(self.trace_id)
        _current_tracer.set(self)

        logger.info(f'[TRACE:{self.trace_id}] ═══ START ═══ input="{self.user_input}"')

    @contextmanager
    def span(self, node_name: str, input_summary: str = "") -> Generator[TraceSpan, None, None]:
        """
        用于对 span 计时的上下文管理器。

        支持嵌套：如果在另一个 span 内调用，则会创建子 span。

        用法：
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

        # 处理嵌套：若存在活跃的父 span，则作为子 span 添加
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
        """将一次 LLM 推理调用记录为当前活跃 span 的子 span。"""
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
        # 挂载到当前活跃 span 或顶层
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
        """将一次工具调用记录为当前活跃 span 的子 span。"""
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
        结束追踪并写入结果。

        Args:
            processing_path: 所采用的处理路径（fast/normal/heavy/degraded）
            final_output: 最终输出文本

        Returns:
            包含 trace 结果的摘要字典
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
                phase_breakdown.append(
                    {
                        "node": s.node_name,
                        "duration_ms": s.duration_ms,
                        "percentage": round(s.duration_ms / total_ms * 100, 1) if total_ms > 0 else 0,
                        "is_slow": s.is_slow,
                    }
                )

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

        # 记录带瓶颈高亮的摘要
        bottleneck_info = ""
        if slow_spans:
            bottleneck_info = " | BOTTLENECKS: " + ", ".join(f"{s.node_name}({s.duration_ms}ms)" for s in slow_spans)
        logger.info(
            f"[TRACE:{self.trace_id}] ═══ END ═══ Total={total_ms}ms "
            f"Path={processing_path} Status={status} Spans={len(self.spans)}"
            f"{bottleneck_info}"
        )

        # 写入文件
        self._write_trace_file(summary)

        # 添加到最近 trace 索引（摘要，不含完整 spans）
        _recent_traces.append(
            {
                "trace_id": self.trace_id,
                "user_input": self.user_input,
                "processing_path": processing_path,
                "total_ms": total_ms,
                "status": status,
                "slow_spans": summary["slow_spans"],
                "timestamp": summary["timestamp"],
            }
        )

        # 清理上下文
        _current_tracer.set(None)

        return summary

    def _write_trace_file(self, summary: dict) -> None:
        """将 trace 写入 JSON 文件，供离线分析。"""
        try:
            TRACES_DIR.mkdir(parents=True, exist_ok=True)
            trace_file = TRACES_DIR / f"{self.trace_id}.json"
            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
            logger.debug(f"[TRACE:{self.trace_id}] Written to {trace_file}")
        except Exception as e:
            logger.warning(f"[TRACE:{self.trace_id}] Failed to write trace file: {e}")

    def get_summary_line(self) -> str:
        """获取一行摘要，便于快速展示。"""
        total_ms = round((time.time() - self.start_time) * 1000, 2)
        has_error = any(s.error for s in self.spans)
        slow_count = sum(1 for s in self.spans if s.is_slow)
        status = "ERROR" if has_error else (f"SLOW({slow_count})" if slow_count else "OK")
        return f"[TRACE:{self.trace_id}] {total_ms}ms | " f"Spans={len(self.spans)} | Status={status}"


# =============================================================================
# 节点级追踪装饰器 [v7.2]
# =============================================================================


def traced_node(node_name: str):
    """
    用于 LangGraph 节点函数的装饰器，自动追踪执行过程。

    为异步节点函数包装计时、输入/输出捕获和错误跟踪。
    若当前存在活跃的 RequestTracer，则会与之集成。

    用法：
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
                # 使用 tracer 的 span 进行完整集成
                input_summary = state.get("user_input", "")[:100]
                with tracer.span(node_name, input_summary=input_summary) as span:
                    try:
                        result = await func(state)
                        # 捕获关键输出字段
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
                # 回退：独立的计时日志（无活跃 tracer 时）
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
# 节点级追踪的便捷函数（向后兼容）
# =============================================================================


def trace_node(node_name: str, state: dict) -> tuple[RequestTracer | None, TraceSpan | None]:
    """
    从上下文中获取 tracer 并启动一个 span 的辅助函数。

    返回 (tracer, span) 元组。若无活跃 tracer，则返回 (None, None)。
    注意：调用方需正确使用 span 上下文管理器。推荐使用 @traced_node 装饰器。
    """
    tracer = get_current_tracer()
    if not tracer:
        return None, None
    return tracer, None
