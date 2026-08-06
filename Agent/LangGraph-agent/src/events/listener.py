"""
WebSocket Event Listener [v7.1].

Connects to WSL C++ backend WebSocket (ws://localhost:8081/ws/v1/events).
Subscribes to: alarm / fiber_color / fiber_stats events.
Features:
- Auto-reconnect (5s interval)
- Events written to asyncio.Queue for processing
- Recent event buffer for internal_tools.event_query
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

RECONNECT_INTERVAL = 5.0  # seconds
MAX_RECENT_EVENTS = 100


class EventListener:
    """
    WebSocket event listener with auto-reconnect.

    Subscribes to backend events and pushes them to an asyncio.Queue
    for the event router to process.
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
        """Start the event listener background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info(f"[EventListener] Started, connecting to {self.ws_url}")

    async def stop(self) -> None:
        """Stop the event listener."""
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
        """Main listen loop with auto-reconnect."""
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
        """Connect to WebSocket and listen for events."""
        import websockets

        async with websockets.connect(self.ws_url, ping_interval=20) as ws:
            self._connected = True
            logger.info("[EventListener] Connected to backend WebSocket")

            # Subscribe to event types
            subscribe_msg = json.dumps({
                "action": "subscribe",
                "events": ["alarm", "fiber_color", "fiber_stats"],
            })
            await ws.send(subscribe_msg)

            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

    async def _handle_message(self, raw: str) -> None:
        """Parse and enqueue an event message."""
        try:
            event = json.loads(raw)
            event["_received_at"] = time.time()
            event["_id"] = f"evt_{int(time.time()*1000)}_{len(self._recent_events)}"

            # Store in recent buffer
            self._recent_events.append(event)

            # Push to queue for router processing
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest
                try:
                    self.queue.get_nowait()
                    self.queue.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass

        except json.JSONDecodeError:
            logger.debug(f"[EventListener] Non-JSON message: {raw[:100]}")

    def get_recent_events(self, limit: int = 10, event_type: Optional[str] = None) -> list[dict]:
        """Get recent events (for internal_tools.event_query)."""
        events = list(self._recent_events)
        if event_type:
            events = [e for e in events if e.get("type") == event_type or e.get("event_type") == event_type]
        return events[-limit:]


# =============================================================================
# Singleton
# =============================================================================

_listener_instance: Optional[EventListener] = None


def get_event_listener() -> Optional[EventListener]:
    """Get the event listener singleton."""
    return _listener_instance


def create_event_listener() -> EventListener:
    """Create and register the event listener singleton."""
    global _listener_instance
    if _listener_instance is None:
        _listener_instance = EventListener()
    return _listener_instance
