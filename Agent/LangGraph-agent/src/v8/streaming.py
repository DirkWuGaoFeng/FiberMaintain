"""
v8 流式事件系统 — 工具级中间状态推送.

设计：
- StreamEvent: 事件数据模型
- StreamCallback: 回调协议（由 API 层 / SSE 层注入）
- Collection Agent 确定性路径每完成一个工具调用即 emit 事件
- 用户感知延迟从"总耗时"降为"第一个工具返回时间"

事件类型：
- collection_start: 开始采集
- tool_complete: 单个工具调用完成
- tool_error: 单个工具调用失败
- collection_done: 采集完成
- analysis_start/done: 分析阶段
- expression_done: 输出完成
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional, Protocol

logger = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    COLLECTION_START = "collection_start"
    TOOL_COMPLETE = "tool_complete"
    TOOL_ERROR = "tool_error"
    COLLECTION_DONE = "collection_done"
    ANALYSIS_START = "analysis_start"
    ANALYSIS_DONE = "analysis_done"
    EXPRESSION_DONE = "expression_done"


@dataclass
class StreamEvent:
    """流式事件."""

    type: StreamEventType
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp_ms: float = 0.0


# 回调类型：async def callback(event: StreamEvent) -> None
StreamCallback = Callable[[StreamEvent], Coroutine[Any, Any, None]]


class StreamEmitter:
    """
    流式事件发射器.

    注入到 Agent context 中，Agent 通过 emitter.emit() 推送事件。
    如果没有注入回调（如测试环境），事件静默丢弃。
    """

    def __init__(self, callback: Optional[StreamCallback] = None):
        self._callback = callback
        self._events: list[StreamEvent] = []

    async def emit(
        self,
        event_type: StreamEventType,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """发射事件."""
        import time

        event = StreamEvent(
            type=event_type,
            message=message,
            metadata=metadata or {},
            timestamp_ms=round(time.time() * 1000, 2),
        )
        self._events.append(event)

        if self._callback:
            try:
                await self._callback(event)
            except Exception as e:
                logger.warning(f"[StreamEmitter] Callback error: {e}")

    @property
    def events(self) -> list[StreamEvent]:
        """获取已发射的事件列表（测试/审计用）."""
        return self._events.copy()


# =============================================================================
# 便捷工厂
# =============================================================================


def create_emitter(
    callback: Optional[StreamCallback] = None,
) -> StreamEmitter:
    """创建流式事件发射器."""
    return StreamEmitter(callback=callback)


def create_sse_callback() -> tuple[StreamCallback, asyncio.Queue]:
    """
    创建 SSE 兼容的回调 + 队列.

    API 层从队列中消费事件，转为 SSE text/event-stream 推送。
    """
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

    async def callback(event: StreamEvent) -> None:
        await queue.put(event)

    return callback, queue
