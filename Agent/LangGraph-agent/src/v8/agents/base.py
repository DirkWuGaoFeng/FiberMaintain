"""
BaseAgent — 三层 Agent 的统一抽象.

每个 Agent:
- 接收 ExecutionPlan + 上下文
- 执行自己的职责
- 返回 AgentResult
- 记录 audit_trail

韧性保障：
- 分层超时（每层独立 SLA）
- LLM 熔断器集成（超时/异常触发熔断计数）
- 异常兜底（永不崩溃）
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from ..models import AgentLayer, AgentResult, ExecutionPlan
from ..resilience import AgentTimeout, CircuitOpenError, get_llm_breaker
from ..metrics import record_agent_execution

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """三层 Agent 基类."""

    @property
    @abstractmethod
    def layer(self) -> AgentLayer:
        """Agent 所属层."""
        ...

    @abstractmethod
    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        """
        执行 Agent 职责.

        Args:
            plan: Lead Router 生成的执行计划
            context: 运行时上下文（user_input, normalized_params, 前序 Agent 结果等）

        Returns:
            AgentResult 统一格式
        """
        ...

    async def run(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        """带超时、熔断和异常兜底的执行入口."""
        trace_id = context.get("trace_id", "")
        start = time.time()
        timeout = self._get_timeout(context)
        logger.info(
            f"[TRACE:{trace_id}] [{self.layer.value}_agent] START "
            f"(timeout={timeout}s)"
        )

        try:
            result = await asyncio.wait_for(
                self.execute(plan, context),
                timeout=timeout,
            )
            result.latency_ms = round((time.time() - start) * 1000, 2)
            logger.info(
                f"[TRACE:{trace_id}] [{self.layer.value}_agent] "
                f"OK {result.latency_ms}ms success={result.success}"
            )
            # 成功时记录（恢复熔断器）
            breaker = get_llm_breaker()
            await breaker.record_success()
            # 指标埋点
            record_agent_execution(
                self.layer.value,
                context.get("execution_mode", "default"),
                result.latency_ms,
                result.success,
            )
            return result

        except asyncio.TimeoutError:
            elapsed = round((time.time() - start) * 1000, 2)
            logger.error(
                f"[TRACE:{trace_id}] [{self.layer.value}_agent] "
                f"TIMEOUT {elapsed}ms (limit={timeout}s)"
            )
            breaker = get_llm_breaker()
            await breaker.record_failure()
            return AgentResult(
                layer=self.layer,
                success=False,
                error=f"{self.layer.value} 超时 ({timeout}s)",
                data=self._degraded_data("timeout"),
                latency_ms=elapsed,
            )

        except CircuitOpenError as e:
            elapsed = round((time.time() - start) * 1000, 2)
            logger.warning(
                f"[TRACE:{trace_id}] [{self.layer.value}_agent] "
                f"CIRCUIT_OPEN {elapsed}ms"
            )
            return AgentResult(
                layer=self.layer,
                success=False,
                error="LLM 熔断中，走降级路径",
                data=self._degraded_data("circuit_open"),
                latency_ms=elapsed,
            )

        except Exception as e:
            elapsed = round((time.time() - start) * 1000, 2)
            logger.error(
                f"[TRACE:{trace_id}] [{self.layer.value}_agent] "
                f"ERROR {elapsed}ms error={e}"
            )
            breaker = get_llm_breaker()
            await breaker.record_failure()
            return AgentResult(
                layer=self.layer,
                success=False,
                error=str(e),
                data=self._degraded_data("exception"),
                latency_ms=elapsed,
            )

    def _get_timeout(self, context: dict) -> float:
        """根据 Agent 层和执行模式确定超时 SLA."""
        mode = context.get("execution_mode", "")
        if self.layer == AgentLayer.COLLECTION:
            return AgentTimeout.for_collection(mode or "react")
        elif self.layer == AgentLayer.ANALYSIS:
            return AgentTimeout.for_analysis(mode or "llm")
        elif self.layer == AgentLayer.EXPRESSION:
            return AgentTimeout.for_expression(mode or "template")
        return 30.0  # 默认全局超时

    def _degraded_data(self, reason: str) -> dict[str, Any]:
        """生成降级数据（有损但可用）. SLA 契约：data 永不为空."""
        return {
            "degraded": True,
            "reason": reason,
            "layer": self.layer.value,
            "message": "服务暂时不可用，请稍后重试",
        }
