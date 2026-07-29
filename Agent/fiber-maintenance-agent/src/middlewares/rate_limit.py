"""RateLimitMiddleware：令牌桶限流 10/min, 突发20。"""
from __future__ import annotations
import time, logging
from .base import Middleware, RunContext

logger = logging.getLogger("fiber.mw.ratelimit")


class TokenBucket:
    """令牌桶：rate tokens/sec, burst 最大突发。"""

    def __init__(self, rate: float, burst: int):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()

    def consume(self, n: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    @property
    def available(self) -> float:
        return self._tokens


class RateLimitMiddleware(Middleware):
    """每分钟 10 次请求，突发上限 20。"""

    def __init__(self, rate_per_min: float = 10.0, burst: int = 20):
        self._bucket = TokenBucket(rate=rate_per_min / 60.0, burst=burst)

    async def before_model(self, ctx: RunContext) -> None:
        if not self._bucket.consume():
            ctx.meta["rate_limited"] = True
            logger.warning("RateLimit: 请求被限流, available=%.1f",
                           self._bucket.available)
            raise RateLimitExceeded("请求频率超限，请稍后重试")


class RateLimitExceeded(Exception):
    pass
