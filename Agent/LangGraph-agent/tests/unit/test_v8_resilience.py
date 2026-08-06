"""v8 韧性层测试 — 超时 + 熔断器."""
import asyncio

import pytest

from src.v8.agents.base import BaseAgent
from src.v8.models import AgentLayer, AgentResult, ExecutionPlan
from src.v8.resilience import (
    AgentTimeout,
    BreakerState,
    CircuitOpenError,
    LLMCircuitBreaker,
    get_llm_breaker,
    reset_llm_breaker,
)


# =============================================================================
# AgentTimeout 测试
# =============================================================================


class TestAgentTimeout:
    def test_collection_deterministic(self):
        assert AgentTimeout.for_collection("deterministic") == 5.0

    def test_collection_react(self):
        assert AgentTimeout.for_collection("react") == 20.0

    def test_analysis_rule(self):
        assert AgentTimeout.for_analysis("rule") == 1.0

    def test_analysis_llm(self):
        assert AgentTimeout.for_analysis("llm") == 15.0

    def test_expression_template(self):
        assert AgentTimeout.for_expression("template") == 2.0

    def test_expression_llm(self):
        assert AgentTimeout.for_expression("llm") == 10.0


# =============================================================================
# LLMCircuitBreaker 测试
# =============================================================================


class TestLLMCircuitBreaker:
    @pytest.fixture(autouse=True)
    def setup(self):
        reset_llm_breaker()
        yield
        reset_llm_breaker()

    @pytest.mark.asyncio
    async def test_starts_closed(self):
        breaker = LLMCircuitBreaker(failure_threshold=3)
        assert breaker.state == BreakerState.CLOSED
        assert breaker.is_available

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        breaker = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        await breaker.record_failure()
        await breaker.record_failure()
        assert breaker.state == BreakerState.CLOSED
        await breaker.record_failure()
        assert breaker.state == BreakerState.OPEN
        assert not breaker.is_available

    @pytest.mark.asyncio
    async def test_check_raises_when_open(self):
        breaker = LLMCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        await breaker.record_failure()
        await breaker.record_failure()
        with pytest.raises(CircuitOpenError):
            await breaker.check()

    @pytest.mark.asyncio
    async def test_half_open_after_cooldown(self):
        breaker = LLMCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        await breaker.record_failure()
        await breaker.record_failure()
        assert breaker.state == BreakerState.OPEN

        await asyncio.sleep(0.15)  # 等待 cooldown
        await breaker.check()  # 应该转为 HALF_OPEN
        assert breaker.state == BreakerState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_closes_on_probe_success(self):
        breaker = LLMCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        await breaker.record_failure()
        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.check()  # -> HALF_OPEN
        await breaker.record_success()
        assert breaker.state == BreakerState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_reopens_on_probe_failure(self):
        breaker = LLMCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        await breaker.record_failure()
        await breaker.record_failure()
        await asyncio.sleep(0.15)
        await breaker.check()  # -> HALF_OPEN
        await breaker.record_failure()
        assert breaker.state == BreakerState.OPEN

    @pytest.mark.asyncio
    async def test_success_decrements_failure_count(self):
        breaker = LLMCircuitBreaker(failure_threshold=3)
        await breaker.record_failure()
        await breaker.record_failure()
        assert breaker.failure_count == 2
        await breaker.record_success()
        assert breaker.failure_count == 1

    def test_get_status(self):
        breaker = LLMCircuitBreaker(failure_threshold=3, name="test")
        status = breaker.get_status()
        assert status["name"] == "test"
        assert status["state"] == "closed"
        assert status["threshold"] == 3


# =============================================================================
# BaseAgent 超时集成测试
# =============================================================================


class _SlowAgent(BaseAgent):
    """模拟慢 Agent."""

    def __init__(self, delay: float):
        self._delay = delay

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.COLLECTION

    async def execute(self, plan, context):
        await asyncio.sleep(self._delay)
        return AgentResult(layer=self.layer, success=True, data={"ok": True})


class TestBaseAgentTimeout:
    @pytest.fixture(autouse=True)
    def setup(self):
        reset_llm_breaker()
        yield
        reset_llm_breaker()

    @pytest.mark.asyncio
    async def test_timeout_triggers(self):
        """超时后返回 success=False."""
        agent = _SlowAgent(delay=10.0)  # 远超 5s 超时
        plan = ExecutionPlan()
        ctx = {"trace_id": "t1", "execution_mode": "deterministic"}
        result = await agent.run(plan, ctx)
        assert not result.success
        assert "超时" in result.error

    @pytest.mark.asyncio
    async def test_timeout_records_breaker_failure(self):
        """超时触发熔断器计数."""
        agent = _SlowAgent(delay=10.0)
        plan = ExecutionPlan()
        ctx = {"trace_id": "t1", "execution_mode": "deterministic"}

        breaker = get_llm_breaker()
        await agent.run(plan, ctx)
        assert breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_fast_agent_no_timeout(self):
        """快速 Agent 正常完成."""
        agent = _SlowAgent(delay=0.01)
        plan = ExecutionPlan()
        ctx = {"trace_id": "t1", "execution_mode": "deterministic"}
        result = await agent.run(plan, ctx)
        assert result.success
        assert result.data == {"ok": True}
