"""Sub-Agent FIFO 调度器：最大 5 并发，严格 FIFO 排队。"""
from __future__ import annotations
import asyncio, collections, logging

from src.settings import settings
from src.monitoring.metrics import SUBAGENT_CONCURRENT, SUBAGENT_QUEUE

logger = logging.getLogger("fiber.scheduler")

class FIFOSemaphore:
    """严格 FIFO 信号量（asyncio.Semaphore 不保证顺序，此处显式排队）。"""
    def __init__(self, limit: int):
        self._limit = limit
        self._running = 0
        self._waiters: collections.deque[asyncio.Future] = collections.deque()

    async def acquire(self) -> None:
        if self._running < self._limit and not self._waiters:
            self._running += 1
            return
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        SUBAGENT_QUEUE.set(len(self._waiters))
        try:
            await fut
        except asyncio.CancelledError:
            self._waiters.remove(fut) if fut in self._waiters else None
            raise

    def release(self) -> None:
        while self._waiters:
            fut = self._waiters.popleft()
            SUBAGENT_QUEUE.set(len(self._waiters))
            if not fut.done():
                fut.set_result(None)
                return
        self._running = max(0, self._running - 1)

    async def __aenter__(self):
        await self.acquire()
        SUBAGENT_CONCURRENT.inc()
        return self

    async def __aexit__(self, *exc):
        SUBAGENT_CONCURRENT.dec()
        self.release()


_semaphore: FIFOSemaphore | None = None

def get_semaphore() -> FIFOSemaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = FIFOSemaphore(settings.agents["subagents"]["max_concurrent"])
    return _semaphore


async def dispatch_subagent(name: str, instruction: str,
                            context: str = "") -> str:
    """FIFO 派遣 Sub-Agent，带单任务超时（15s）。"""
    from .sub_agents import run_subagent
    import time
    timeout = settings.agents["subagents"]["task_timeout_seconds"]
    queue_len = len(get_semaphore()._waiters)
    logger.info("[Scheduler] 派遣 %s queue=%d timeout=%ss",
                name, queue_len, timeout)
    t0 = time.perf_counter()
    async with get_semaphore():
        wait_ms = (time.perf_counter() - t0) * 1000
        if wait_ms > 50:
            logger.info("[Scheduler] %s 排队等待 %.0fms", name, wait_ms)
        try:
            result = await asyncio.wait_for(
                run_subagent(name, instruction, context), timeout=timeout)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info("[Scheduler] %s 完成 result_len=%d total=%.0fms",
                        name, len(result), elapsed)
            return result
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.error("[Scheduler] %s 超时 total=%.0fms timeout=%ss",
                         name, elapsed, timeout)
            return f"[{name}] 执行超时（>{timeout}s），该子任务已跳过。"