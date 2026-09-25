"""
v8 三层架构端到端集成测试.

使用 mock 后端（不需要真实 C++ 服务），验证完整流程：
User Input → Lead Router → Orchestrator → Collection → Analysis → Expression → Response
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.v8.lead_router import LeadRouter
from src.v8.models import AgentLayer, AgentResult, ExecutionPlan, V8State
from src.v8.orchestrator import Orchestrator


class TestV8EndToEnd:
    """完整流程测试."""

    @pytest.mark.asyncio
    async def test_spanloss_normal_flow(self):
        """正常跨段损耗查询 → 完整三层流程."""
        router = LeadRouter()
        orch = Orchestrator()

        # Lead Router 解析
        plan = await router.resolve(
            "查看光纤1的跨段损耗",
            {"fiber_ids": [1]},
            trace_id="e2e-001",
        )
        assert plan.scenario_id != ""

        # Mock Collection 返回正常数据
        with patch.object(orch.collection_agent, "run", new_callable=AsyncMock) as mock_collect:
            mock_collect.return_value = AgentResult(
                layer=AgentLayer.COLLECTION,
                success=True,
                data={"raw_summary": "光纤1 跨段损耗 2.8 dB，OOP -5.2 dBm"},
                llm_calls=1,
            )

            state = V8State(
                user_input="查看光纤1的跨段损耗",
                trace_id="e2e-001",
                execution_plan=plan,
                normalized_params={"fiber_ids": [1]},
            )
            result = await orch.execute(state)

            assert result.final_status in ("NORMAL", "WARNING", "CRITICAL")
            assert result.final_response != ""
            assert result.loop_context.terminated_reason == "complete"
            assert result.total_llm_calls >= 1

    @pytest.mark.asyncio
    async def test_critical_alarm_flow(self):
        """严重告警 → CRITICAL 输出."""
        orch = Orchestrator()

        with patch.object(orch.collection_agent, "run", new_callable=AsyncMock) as mock_collect:
            mock_collect.return_value = AgentResult(
                layer=AgentLayer.COLLECTION,
                success=True,
                data={"raw_summary": "光纤3 跨段损耗 9.5 dB，OOP -15.0 dBm"},
                llm_calls=1,
            )

            plan = ExecutionPlan(
                scenario_id="spanloss_check",
                tools=["fiber_spanloss_query"],
                output_format="narrative",
            )
            state = V8State(
                user_input="光纤3怎么了",
                trace_id="e2e-002",
                execution_plan=plan,
            )
            result = await orch.execute(state)

            assert result.final_status == "CRITICAL"
            assert "🚨" in result.final_response

    @pytest.mark.asyncio
    async def test_loop_terminates_at_max_rounds(self):
        """循环在 max_rounds 时终止."""
        orch = Orchestrator()

        round_counter = {"n": 0}

        async def always_need_more(plan, ctx):
            round_counter["n"] += 1
            return AgentResult(
                layer=AgentLayer.ANALYSIS,
                success=True,
                data={"verdict": {"status": "UNKNOWN", "findings": []}},
                needs_more_data=True,
                additional_query={"reason": "需要更多数据", "tool": "alarm_query"},
            )

        async def collection_with_varying_data(plan, ctx):
            return AgentResult(
                layer=AgentLayer.COLLECTION,
                success=True,
                data={"raw_summary": f"data round {round_counter['n']} unique"},
                llm_calls=1,
            )

        with (
            patch.object(orch.collection_agent, "run", side_effect=collection_with_varying_data),
            patch.object(orch.analysis_agent, "run", side_effect=always_need_more),
            patch.object(orch.expression_agent, "run", new_callable=AsyncMock) as me,
        ):
            me.return_value = AgentResult(
                layer=AgentLayer.EXPRESSION,
                success=True,
                data={"response": "❓ 数据不足", "format": "narrative"},
            )

            plan = ExecutionPlan(max_loop_rounds=5)  # 需要更多轮次以触发熔断阈值
            state = V8State(user_input="test", trace_id="e2e-003", execution_plan=plan)
            result = await orch.execute(state)

            # [P0] Agent 熔断器在达到 max_rounds 前检测到循环
            assert result.loop_context.round >= 3
            assert result.loop_context.terminated_reason in (
                "max_rounds",
                "analysis_loop_detected",
            )
