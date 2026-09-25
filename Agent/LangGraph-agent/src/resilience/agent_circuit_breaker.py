"""
Agent 级熔断器 (AgentCircuitBreaker).

【设计原则】
对应 AI Agent 设计原则 Chapter 1 纠正机制：
  - 检测 Agent 死循环模式并主动终止
  - 在 Collection↔Analysis 循环中检测无进展
  - 返回降级结果而非无限循环

【熔断触发条件】
1. Analysis 连续 N 次返回 needs_more_data=True
2. Collection 数据签名连续 N 轮不变
3. LLM 调用次数超过预算
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CircuitBreakerVerdict(BaseModel):
    """熔断器裁决."""

    should_terminate: bool = False
    reason: Optional[str] = None
    loop_count: int = 0
    llm_calls: int = 0
    data_signature_changes: int = 0


class AgentCircuitBreaker:
    """Agent 级三态熔断器.

    检测模式:
    1. analysis_loop_detected: Analysis 连续 needs_more_data
    2. no_progress: 数据签名不变
    3. llm_budget_exhausted: LLM 调用预算耗尽
    """

    def __init__(
        self,
        max_analysis_loops: int = 3,
        max_no_progress_loops: int = 3,
        max_llm_budget: int = 10,
    ):
        self._max_analysis_loops = max_analysis_loops
        self._max_no_progress_loops = max_no_progress_loops
        self._max_llm_budget = max_llm_budget

        self._loop_count = 0
        self._consecutive_needs_more_data = 0
        self._last_data_signature: Optional[str] = None
        self._no_progress_count = 0
        self._llm_calls = 0
        self._start_time: Optional[float] = None

    @property
    def loop_count(self) -> int:
        return self._loop_count

    @property
    def llm_calls(self) -> int:
        return self._llm_calls

    def record_analysis_result(self, needs_more_data: bool, data_signature: str) -> None:
        """记录一轮 Analysis 结果."""
        self._loop_count += 1

        # 1. needs_more_data 追踪
        if needs_more_data:
            self._consecutive_needs_more_data += 1
        else:
            self._consecutive_needs_more_data = 0

        # 2. 数据签名变化追踪
        if self._last_data_signature is not None:
            if data_signature == self._last_data_signature:
                self._no_progress_count += 1
            else:
                self._no_progress_count = 0
        self._last_data_signature = data_signature

    def record_llm_call(self) -> None:
        """记录一次 LLM 调用."""
        self._llm_calls += 1

    def set_start_time(self) -> None:
        """记录开始时间."""
        self._start_time = time.time()

    def check(self) -> CircuitBreakerVerdict:
        """检查是否应熔断.

        Returns:
            CircuitBreakerVerdict: 熔断器裁决
        """
        # 1. Analysis 循环检测
        if self._consecutive_needs_more_data >= self._max_analysis_loops:
            logger.warning(
                f"[AgentCircuitBreaker] Analysis loop detected: "
                f"{self._consecutive_needs_more_data} consecutive needs_more_data"
            )
            return CircuitBreakerVerdict(
                should_terminate=True,
                reason="analysis_loop_detected",
                loop_count=self._loop_count,
                llm_calls=self._llm_calls,
                data_signature_changes=self._no_progress_count,
            )

        # 2. 无进展检测
        if self._no_progress_count >= self._max_no_progress_loops:
            logger.warning(
                f"[AgentCircuitBreaker] No progress: " f"{self._no_progress_count} unchanged data signatures"
            )
            return CircuitBreakerVerdict(
                should_terminate=True,
                reason="no_progress",
                loop_count=self._loop_count,
                llm_calls=self._llm_calls,
                data_signature_changes=self._no_progress_count,
            )

        # 3. LLM 预算检测
        if self._llm_calls >= self._max_llm_budget:
            logger.warning(
                f"[AgentCircuitBreaker] LLM budget exhausted: " f"{self._llm_calls} >= {self._max_llm_budget}"
            )
            return CircuitBreakerVerdict(
                should_terminate=True,
                reason="llm_budget_exhausted",
                loop_count=self._loop_count,
                llm_calls=self._llm_calls,
                data_signature_changes=self._no_progress_count,
            )

        return CircuitBreakerVerdict(
            should_terminate=False,
            loop_count=self._loop_count,
            llm_calls=self._llm_calls,
            data_signature_changes=self._no_progress_count,
        )

    def reset(self) -> None:
        """重置熔断器（新会话时调用）."""
        self._loop_count = 0
        self._consecutive_needs_more_data = 0
        self._last_data_signature = None
        self._no_progress_count = 0
        self._llm_calls = 0
        self._start_time = None

    def get_degraded_result(self, reason: str, collection_data: Optional[dict] = None) -> dict:
        """生成降级结果（熔断器触发时使用）."""
        return {
            "status": "DEGRADED",
            "degradation_reason": reason,
            "message": f"分析循环已达安全上限（{self._loop_count} 轮），" f"建议人工介入或补充更多数据后重试。",
            "partial_data": collection_data,
            "metadata": {
                "circuit_breaker_triggered": True,
                "loop_count": self._loop_count,
                "llm_calls": self._llm_calls,
            },
        }


# =============================================================================
# 单例工厂
# =============================================================================

_breaker: Optional[AgentCircuitBreaker] = None


def get_agent_circuit_breaker(
    max_analysis_loops: int = 3,
    max_no_progress_loops: int = 3,
    max_llm_budget: int = 10,
) -> AgentCircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = AgentCircuitBreaker(
            max_analysis_loops=max_analysis_loops,
            max_no_progress_loops=max_no_progress_loops,
            max_llm_budget=max_llm_budget,
        )
    return _breaker
