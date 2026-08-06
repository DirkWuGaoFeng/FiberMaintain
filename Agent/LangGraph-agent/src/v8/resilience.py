"""
v8 韧性层 — 分层超时 + LLM Circuit Breaker.

设计原则：
- 每层 Agent 有独立 SLA（超时后走降级路径）
- LLM 调用有全局熔断器（连续失败 → 熔断 → 期间所有 LLM 走规则/模板）
- 复用 v7.1 CircuitBreaker 三态模型（CLOSED → OPEN → HALF_OPEN）
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 分层超时配置
# =============================================================================


class AgentTimeout:
    """每层 Agent 的超时 SLA（秒）."""

    # Collection Agent
    COLLECTION_DETERMINISTIC: float = 5.0
    COLLECTION_REACT: float = 20.0

    # Analysis Agent
    ANALYSIS_RULE: float = 1.0
    ANALYSIS_LLM: float = 15.0

    # Expression Agent
    EXPRESSION_TEMPLATE: float = 2.0
    EXPRESSION_LLM: float = 10.0

    # LeadRouter
    ROUTER_LLM: float = 5.0

    @classmethod
    def for_collection(cls, mode: str) -> float:
        if mode == "deterministic":
            return cls.COLLECTION_DETERMINISTIC
        return cls.COLLECTION_REACT

    @classmethod
    def for_analysis(cls, mode: str) -> float:
        if mode == "rule":
            return cls.ANALYSIS_RULE
        return cls.ANALYSIS_LLM

    @classmethod
    def for_expression(cls, mode: str) -> float:
        if mode == "template":
            return cls.EXPRESSION_TEMPLATE
        return cls.EXPRESSION_LLM


# =============================================================================
# LLM Circuit Breaker
# =============================================================================


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class LLMCircuitBreaker:
    """
    LLM 专用熔断器.

    - 连续 failure_threshold 次失败 → OPEN（拒绝所有 LLM 调用）
    - cooldown 后 → HALF_OPEN（允许一次探测）
    - 探测成功 → CLOSED（恢复正常）
    - 探测失败 → 重新 OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        name: str = "llm",
    ):
        self.state = BreakerState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.name = name
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def is_available(self) -> bool:
        """当前是否允许 LLM 调用（无锁快速检查）."""
        if self.state == BreakerState.CLOSED:
            return True
        if self.state == BreakerState.OPEN:
            # 检查 cooldown 是否已过
            if self._opened_at and (
                time.monotonic() - self._opened_at >= self.cooldown_seconds
            ):
                return True  # 将转为 HALF_OPEN
            return False
        return True  # HALF_OPEN 允许探测

    async def check(self) -> None:
        """检查是否允许调用. 熔断时抛出 CircuitOpenError."""
        async with self._lock:
            if self.state == BreakerState.CLOSED:
                return
            if self.state == BreakerState.OPEN:
                if (
                    self._opened_at
                    and time.monotonic() - self._opened_at >= self.cooldown_seconds
                ):
                    self.state = BreakerState.HALF_OPEN
                    logger.info(
                        f"[CircuitBreaker:{self.name}] OPEN -> HALF_OPEN"
                    )
                    return
                raise CircuitOpenError(
                    f"LLM circuit breaker '{self.name}' OPEN, "
                    f"cooldown {self.cooldown_seconds}s"
                )
            # HALF_OPEN: 允许探测

    async def record_success(self) -> None:
        """记录成功."""
        async with self._lock:
            if self.state == BreakerState.HALF_OPEN:
                self.state = BreakerState.CLOSED
                self.failure_count = 0
                logger.info(
                    f"[CircuitBreaker:{self.name}] HALF_OPEN -> CLOSED"
                )
            elif self.state == BreakerState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)

    async def record_failure(self) -> None:
        """记录失败. 可能触发熔断."""
        async with self._lock:
            self.failure_count += 1
            if self.state == BreakerState.HALF_OPEN:
                self.state = BreakerState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    f"[CircuitBreaker:{self.name}] HALF_OPEN -> OPEN"
                )
            elif self.state == BreakerState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    self.state = BreakerState.OPEN
                    self._opened_at = time.monotonic()
                    logger.warning(
                        f"[CircuitBreaker:{self.name}] CLOSED -> OPEN "
                        f"(failures={self.failure_count})"
                    )

    def get_status(self) -> dict[str, Any]:
        """获取熔断器状态（供 /metrics 端点）."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }


class CircuitOpenError(Exception):
    """熔断器开启时抛出."""

    pass


# =============================================================================
# 全局单例
# =============================================================================

_llm_breaker: Optional[LLMCircuitBreaker] = None


def get_llm_breaker() -> LLMCircuitBreaker:
    """获取全局 LLM 熔断器单例."""
    global _llm_breaker
    if _llm_breaker is None:
        _llm_breaker = LLMCircuitBreaker(
            failure_threshold=3,
            cooldown_seconds=60.0,
            name="ollama",
        )
    return _llm_breaker


def reset_llm_breaker() -> None:
    """重置熔断器（测试用）."""
    global _llm_breaker
    _llm_breaker = None
