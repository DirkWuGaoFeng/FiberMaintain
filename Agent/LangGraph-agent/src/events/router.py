"""
事件路由器 [v7.1]。

将监听器队列中的事件路由到相应的处理器：
- CRITICAL 告警 → 触发主动诊断
- GREEN→RED 颜色变化 → 触发主动诊断
- stats_update → 更新 LocalCache

作为后台 asyncio 任务运行，从 EventListener.queue 消费事件。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EventRouter:
    """
    事件路由引擎。

    从监听器队列消费事件并分发给相应的处理器。
    """

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self, queue: asyncio.Queue) -> None:
        """启动事件路由器后台任务。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._route_loop(queue))
        logger.info("[EventRouter] Started")

    async def stop(self) -> None:
        """停止事件路由器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[EventRouter] Stopped")

    async def _route_loop(self, queue: asyncio.Queue) -> None:
        """主路由循环。"""
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
        """将单个事件路由到相应的处理器。"""
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
        """处理告警事件：CRITICAL 触发主动诊断。"""
        level = event.get("alarm_level", event.get("level", ""))
        fiber_id = event.get("fiber_id")

        if level in ("CRITICAL", "MAJOR"):
            logger.warning(f"[EventRouter] CRITICAL alarm on fiber {fiber_id}, triggering proactive diagnosis")
            await self._trigger_proactive(event, reason="critical_alarm")
        else:
            logger.info(f"[EventRouter] Alarm ({level}) on fiber {fiber_id}, logged only")

    async def _handle_color_change(self, event: dict) -> None:
        """处理光纤颜色变化：GREEN→RED 触发主动诊断。"""
        old_color = event.get("old_color", "")
        new_color = event.get("new_color", event.get("color", ""))
        fiber_id = event.get("fiber_id")

        if new_color == "RED" and old_color in ("GREEN", "YELLOW"):
            logger.warning(f"[EventRouter] Fiber {fiber_id} color {old_color}→RED, triggering proactive diagnosis")
            await self._trigger_proactive(event, reason="color_escalation")
        else:
            logger.info(f"[EventRouter] Fiber {fiber_id} color change: {old_color}→{new_color}")

    async def _handle_stats_update(self, event: dict) -> None:
        """处理统计更新事件：写入 LocalCache。"""
        try:
            from ..cache.local_cache import get_local_cache

            cache = get_local_cache()
            if cache:
                await cache.set("stats:realtime", event.get("data", event), ttl=300)
                logger.debug("[EventRouter] Stats cache updated")
        except Exception as e:
            logger.debug(f"[EventRouter] Cache update failed: {e}")

    async def _trigger_proactive(self, event: dict, reason: str) -> None:
        """触发主动诊断子图。"""
        try:
            from ..graph.subgraphs.proactive import run_proactive_diagnosis

            asyncio.create_task(run_proactive_diagnosis(event, reason=reason))
        except ImportError:
            logger.warning("[EventRouter] Proactive module not available")
        except Exception as e:
            logger.error(f"[EventRouter] Proactive trigger failed: {e}")


# =============================================================================
# 单例
# =============================================================================

_router_instance: Optional[EventRouter] = None


def get_event_router() -> EventRouter:
    """获取或创建事件路由器单例。"""
    global _router_instance
    if _router_instance is None:
        _router_instance = EventRouter()
    return _router_instance
