"""
Rate limit callback: token bucket rate limiter (10 req/min).
"""

from __future__ import annotations

import logging
import time

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: float = 10, burst: int = 20):
        self.rate = rate  # tokens per minute
        self.burst = burst
        self._tokens = float(burst)
        self._last_time = time.monotonic()

    def acquire(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._last_time
        self._last_time = now
        # Add tokens based on elapsed time
        self._tokens = min(self.burst, self._tokens + elapsed * (self.rate / 60.0))
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RateLimitCallback(BaseCallbackHandler):
    """Rate limit callback: enforces 10 requests/minute."""

    def __init__(self):
        self.bucket = TokenBucket(rate=10, burst=20)

    def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs) -> None:
        if not self.bucket.acquire():
            raise RuntimeError("Rate limit exceeded: too many requests per minute")
