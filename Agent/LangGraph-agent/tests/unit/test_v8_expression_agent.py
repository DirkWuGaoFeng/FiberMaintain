"""Expression Agent 单元测试."""
import pytest

from src.v8.agents.expression_agent import ExpressionAgent
from src.v8.models import AgentLayer, ExecutionPlan


class TestExpressionAgent:
    def test_layer(self):
        agent = ExpressionAgent()
        assert agent.layer == AgentLayer.EXPRESSION

    @pytest.mark.asyncio
    async def test_narrative_normal(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {
                "verdict": {"status": "NORMAL", "findings": ["跨段损耗 2.5dB → NORMAL"]}
            }
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert "✅" in result.data["response"]
        assert "NORMAL" in result.data["response"]

    @pytest.mark.asyncio
    async def test_narrative_critical(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {
                "verdict": {
                    "status": "CRITICAL",
                    "findings": ["跨段损耗 9.0dB → CRITICAL"],
                    "suggestion": "立即安排现场检修",
                }
            }
        }
        result = await agent.execute(plan, ctx)
        assert "🚨" in result.data["response"]
        assert "建议" in result.data["response"]

    @pytest.mark.asyncio
    async def test_table_format(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="table")
        ctx = {"analysis_data": {"verdict": {"status": "WARNING", "findings": ["OOP异常"]}}}
        result = await agent.execute(plan, ctx)
        assert "|" in result.data["response"]

    @pytest.mark.asyncio
    async def test_raw_format(self):
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="raw")
        ctx = {"analysis_data": {"verdict": {"status": "NORMAL", "findings": []}}}
        result = await agent.execute(plan, ctx)
        assert '"status"' in result.data["response"]
