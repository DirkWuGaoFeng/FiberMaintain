"""
Event Router [v7.1].

Routes events from the listener queue to appropriate handlers:
- CRITICAL alarm → trigger proactive diagnosis
- GREEN→RED color change → trigger proactive diagnosis
- stats_update → update LocalCache

Runs as a background asyncio task consuming from EventListener.queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EventRouter:
    """
    Event routing engine.

    Consumes events from the listener queue and dispatches to handlers.
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self, queue: asyncio.Queue) -> None:
        """Start the event router background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._route_loop(queue))
        logger.info("[EventRouter] Started")

    async def stop(self) -> None:
        """Stop the event router."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[EventRouter] Stopped")

    async def _route_loop(self, queue: asyncio.Queue) -> None:
        """Main routing loop."""
        while self._running:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EventRouter] Dispatch error: {e}")

    async def _dispatch(self, event: dict) -> None:
        """Route a single event to the appropriate handler."""
        event_type = event.get("type", event.get("event_type", ""))

        if event_type == "alarm":
            await self._handle_alarm(event)
        elif event_type == "fiber_color":
            await self._handle_color_change(event)
        elif event_type == "fiber_stats":
            await self._handle_stats_update(event)
        else:
            logger.debug(f"[EventRouter] Unhandled event type: {event_type}")

    async def _handle_alarm(self, event: dict) -> None:
        """Handle alarm event: CRITICAL triggers proactive diagnosis."""
        level = event.get("alarm_level", event.get("level", ""))
        fiber_id = event.get("fiber_id")

        if level in ("CRITICAL", "MAJOR"):
            logger.warning(f"[EventRouter] CRITICAL alarm on fiber {fiber_id}, triggering proactive diagnosis")
            await self._trigger_proactive(event, reason="critical_alarm")
        else:
            logger.info(f"[EventRouter] Alarm ({level}) on fiber {fiber_id}, logged only")

    async def _handle_color_change(self, event: dict) -> None:
        """Handle fiber color change: GREEN→RED triggers proactive diagnosis."""
        old_color = event.get("old_color", "")
        new_color = event.get("new_color", event.get("color", ""))
        fiber_id = event.get("fiber_id")

        if new_color == "RED" and old_color in ("GREEN", "YELLOW"):
            logger.warning(f"[EventRouter] Fiber {fiber_id} color {old_color}→RED, triggering proactive diagnosis")
            await self._trigger_proactive(event, reason="color_escalation")
        else:
            logger.info(f"[EventRouter] Fiber {fiber_id} color change: {old_color}→{new_color}")

    async def _handle_stats_update(self, event: dict) -> None:
        """Handle stats update: write to LocalCache."""
        try:
            from ..cache.local_cache import get_local_cache
            cache = get_local_cache()
            if cache:
                await cache.set("stats:realtime", event.get("data", event), ttl=300)
                logger.debug("[EventRouter] Stats cache updated")
        except Exception as e:
            logger.debug(f"[EventRouter] Cache update failed: {e}")

    async def _trigger_proactive(self, event: dict, reason: str) -> None:
        """Trigger proactive diagnosis sub-graph."""
        try:
            from ..graph.subgraphs.proactive import run_proactive_diagnosis
            asyncio.create_task(run_proactive_diagnosis(event, reason=reason))
        except ImportError:
            logger.warning("[EventRouter] Proactive module not available")
        except Exception as e:
            logger.error(f"[EventRouter] Proactive trigger failed: {e}")


# =============================================================================
# Singleton
# =============================================================================

_router_instance: Optional[EventRouter] = None


def get_event_router() -> EventRouter:
    """Get or create the event router singleton."""
    global _router_instance
    if _router_instance is None:
        _router_instance = EventRouter()
    return _router_instance
