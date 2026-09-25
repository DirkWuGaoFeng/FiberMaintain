"""
WebSocket 事件监听器 [v7.1]。

连接到 WSL C++ 后端的 WebSocket（ws://localhost:8081/ws/v1/events）。
订阅：alarm / fiber_color / fiber_stats 事件。
特性：
- 自动重连（5 秒间隔）
- 事件写入 asyncio.Queue 供处理
- 近期事件缓冲区，供 internal_tools.event_query 使用
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Optional

from ..config import WS_BACKEND_URL

logger = logging.getLogger(__name__)

RECONNECT_INTERVAL = 5.0  # 秒
MAX_RECENT_EVENTS = 100


class EventListener:
    """
    带自动重连的 WebSocket 事件监听器。

    订阅后端事件并将其推送到 asyncio.Queue，
    供事件路由器处理。
    """

    def __init__(self, ws_url: str = ""):
        self.ws_url = ws_url or WS_BACKEND_URL
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._recent_events: deque = deque(maxlen=MAX_RECENT_EVENTS)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """启动事件监听器后台任务。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info(f"[EventListener] Started, connecting to {self.ws_url}")

    async def stop(self) -> None:
        """停止事件监听器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False
        logger.info("[EventListener] Stopped")

    async def _listen_loop(self) -> None:
        """带自动重连的主监听循环。"""
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                if self._running:
                    logger.warning(f"[EventListener] Connection lost: {e}, reconnecting in {RECONNECT_INTERVAL}s")
                    await asyncio.sleep(RECONNECT_INTERVAL)

    async def _connect_and_listen(self) -> None:
        """连接 WebSocket 并监听事件。"""
        import websockets

        async with websockets.connect(self.ws_url, ping_interval=20) as ws:
            self._connected = True
            logger.info("[EventListener] Connected to backend WebSocket")

            # 订阅事件类型
            subscribe_msg = json.dumps(
                {
                    "action": "subscribe",
                    "events": ["alarm", "fiber_color", "fiber_stats"],
                }
            )
            await ws.send(subscribe_msg)

            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

    async def _handle_message(self, raw: str) -> None:
        """解析并排队一个事件消息。"""
        try:
            event = json.loads(raw)
            event["_received_at"] = time.time()
            event["_id"] = f"evt_{int(time.time()*1000)}_{len(self._recent_events)}"

            # 存入近期事件缓冲区
            self._recent_events.append(event)

            # 推入队列供路由器处理
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                # 丢弃最旧的事件
                try:
                    self.queue.get_nowait()
                    self.queue.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

        except json.JSONDecodeError:
            logger.debug(f"[EventListener] Non-JSON message: {raw[:100]}")

    def get_recent_events(self, limit: int = 10, event_type: Optional[str] = None) -> list[dict]:
        """获取近期事件（供 internal_tools.event_query 使用）。"""
        events = list(self._recent_events)
        if event_type:
            events = [e for e in events if e.get("type") == event_type or e.get("event_type") == event_type]
        return events[-limit:]


# =============================================================================
# 单例
# =============================================================================

_listener_instance: Optional[EventListener] = None


def get_event_listener() -> Optional[EventListener]:
    """获取事件监听器单例。"""
    return _listener_instance


def create_event_listener() -> EventListener:
    """创建并注册事件监听器单例。"""
    global _listener_instance
    if _listener_instance is None:
        _listener_instance = EventListener()
    return _listener_instance
