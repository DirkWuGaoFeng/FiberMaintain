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
        ctx = {"analysis_data": {"verdict": {"status": "NORMAL", "findings": ["跨段损耗 2.5dB → NORMAL"]}}}
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

    # ---- 用户记忆偏好注入 [v7.4] ----
    @pytest.mark.asyncio
    async def test_user_memory_injects_table_format(self, monkeypatch):
        """有 user_id + 用户偏好 default_format=table → 输出格式被改写为 table."""

        class FakeManager:
            def inject_preferences(self, user_id, context):
                context = dict(context)
                context["output_format"] = "table"  # 模拟用户偏好
                return context

        monkeypatch.setattr(
            "src.memory.user_memory.get_user_memory_manager",
            lambda: FakeManager(),
        )

        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {
                "verdict": {
                    "status": "NORMAL",
                    "findings": [{"description": "跨段损耗正常"}],
                }
            },
            "user_id": "u-test",
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data["format"] == "table"
        assert "|" in result.data["response"]

    @pytest.mark.asyncio
    async def test_no_user_id_keeps_default_format(self):
        """无 user_id → 跳过注入，保持 plan 默认格式（降级路径）."""
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {"analysis_data": {"verdict": {"status": "NORMAL", "findings": []}}}
        result = await agent.execute(plan, ctx)
        assert result.data["format"] == "narrative"

    @pytest.mark.asyncio
    async def test_user_memory_exception_silently_skipped(self, monkeypatch):
        """注入抛异常 → 静默跳过，不影响正常输出（降级路径）."""

        def _boom(user_id, context):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.memory.user_memory.get_user_memory_manager",
            lambda: type("M", (), {"inject_preferences": _boom})(),
        )

        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {"verdict": {"status": "NORMAL", "findings": ["正常"]}},
            "user_id": "u-test",
        }
        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data["format"] == "narrative"
