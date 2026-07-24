"""ModelDegradationMiddleware：qwen3.6 动态降级 + 熔断器。
primary → fallback → fast → 熔断（60s 半开恢复）。
"""
from __future__ import annotations
import time, logging
from typing import Any

from .base import Middleware, RunContext
from src.settings import settings
from src.monitoring.metrics import MODEL_DEGRADATION

logger = logging.getLogger("fiber.mw.degradation")

LEVELS = ["primary", "fallback", "fast"]

class CircuitBreaker:
    """熔断器：closed → open → half-open → closed。"""
    def __init__(self, threshold: int, recovery: float):
        self.threshold, self.recovery = threshold, recovery
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at >= self.recovery:
            return False          # 进入半开，允许试探
        return True

    @property
    def half_open(self) -> bool:
        return (self.opened_at is not None
                and time.time() - self.opened_at >= self.recovery)

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.time()

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None


class ModelDegradationMiddleware(Middleware):
    def __init__(self) -> None:
        cfg = settings.llm["degradation"]
        self.level = 0                      # 0=primary 1=fallback 2=fast
        self.breaker = CircuitBreaker(cfg["failure_threshold"],
                                      cfg["recovery_seconds"])

    # ── 供 LLMClient 调用 ──
    def current_profile(self) -> str:
        if self.breaker.half_open:
            return LEVELS[0]        # 半开试探 primary
        return LEVELS[self.level]

    def profile_params(self) -> dict:
        return settings.llm["profiles"][self.current_profile()]

    def record_success(self) -> None:
        if self.breaker.half_open or self.level > 0:
            logger.info("模型恢复正常，重置降级状态")
        self.breaker.record_success()
        self.level = 0

    def record_failure(self) -> None:
        self.breaker.record_failure()
        if self.breaker.failures >= self.breaker.threshold:
            if self.level < len(LEVELS) - 1:
                self.level += 1
                MODEL_DEGRADATION.labels(level=LEVELS[self.level]).inc()
                logger.warning("模型降级 → %s", LEVELS[self.level])
                self.breaker.failures = 0
                self.breaker.opened_at = None
            else:
                # 已最低档仍失败 → 熔断
                self.breaker.opened_at = time.time()
                MODEL_DEGRADATION.labels(level="circuit_open").inc()
                logger.error("模型熔断，%ss 后半开恢复", self.breaker.recovery)

    @property
    def circuit_open(self) -> bool:
        return self.breaker.is_open

    # ── Middleware 钩子 ──
    async def after_model(self, ctx: RunContext, response: Any) -> None:
        if response is not None:
            self.record_success()

    async def on_timeout(self, ctx: RunContext) -> None:
        self.record_failure()
        ctx.meta["degradation_level"] = LEVELS[self.level]