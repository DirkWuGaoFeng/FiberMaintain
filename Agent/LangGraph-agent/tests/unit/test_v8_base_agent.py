"""BaseAgent 抽象类测试."""
import pytest

from src.v8.agents.base import BaseAgent
from src.v8.models import AgentLayer, AgentResult, ExecutionPlan


class MockAgent(BaseAgent):
    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.COLLECTION

    async def execute(self, plan, context):
        if context.get("should_fail"):
            raise ValueError("模拟失败")
        return AgentResult(layer=self.layer, data={"ok": True})


class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_run_success(self):
        agent = MockAgent()
        plan = ExecutionPlan(scenario_id="test")
        result = await agent.run(plan, {"trace_id": "t1"})
        assert result.success
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_run_catches_exception(self):
        agent = MockAgent()
        plan = ExecutionPlan()
        result = await agent.run(plan, {"trace_id": "t1", "should_fail": True})
        assert not result.success
        assert "模拟失败" in result.error

    @pytest.mark.asyncio
    async def test_layer_property(self):
        agent = MockAgent()
        assert agent.layer == AgentLayer.COLLECTION
