"""Orchestrator 单元测试."""
import pytest
from unittest.mock import AsyncMock, patch

from src.v8.models import AgentLayer, AgentResult, ExecutionPlan, V8State
from src.v8.orchestrator import Orchestrator


def _mock_collection_result(raw="跨段损耗 3.0 dB"):
    return AgentResult(
        layer=AgentLayer.COLLECTION,
        success=True,
        data={"raw_summary": raw, "tools_used": ["fiber_spanloss_query"]},
        llm_calls=1,
    )


def _mock_analysis_result(status="NORMAL", needs_more=False):
    return AgentResult(
        layer=AgentLayer.ANALYSIS,
        success=True,
        data={
            "verdict": {"status": status, "findings": [f"spanloss → {status}"]},
            "analysis_mode": "rule",
        },
        needs_more_data=needs_more,
        llm_calls=0,
    )


def _mock_expression_result(response="✅ 光纤状态：NORMAL"):
    return AgentResult(
        layer=AgentLayer.EXPRESSION,
        success=True,
        data={"response": response, "format": "narrative"},
    )


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_single_round_complete(self):
        """单轮完成：Collection → Analysis → Expression."""
        orch = Orchestrator()

        with (
            patch.object(
                orch.collection_agent, "run", new_callable=AsyncMock
            ) as mc,
            patch.object(
                orch.analysis_agent, "run", new_callable=AsyncMock
            ) as ma,
            patch.object(
                orch.expression_agent, "run", new_callable=AsyncMock
            ) as me,
        ):
            mc.return_value = _mock_collection_result()
            ma.return_value = _mock_analysis_result()
            me.return_value = _mock_expression_result()

            state = V8State(
                user_input="查看光纤1",
                trace_id="t1",
                execution_plan=ExecutionPlan(scenario_id="test", max_loop_rounds=3),
            )
            result = await orch.execute(state)

            assert result.final_status == "NORMAL"
            assert "✅" in result.final_response
            assert result.loop_context.round == 1
            assert result.loop_context.terminated_reason == "complete"

    @pytest.mark.asyncio
    async def test_multi_round_loop(self):
        """多轮循环：Analysis 要求追加数据."""
        orch = Orchestrator()

        call_count = {"n": 0}

        async def mock_analysis(plan, ctx):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _mock_analysis_result(status="UNKNOWN", needs_more=True)
            return _mock_analysis_result(status="WARNING")

        async def mock_collection(plan, ctx):
            # 每轮返回不同数据，避免无进展检测
            return _mock_collection_result(f"round data {call_count['n']} unique")

        with (
            patch.object(orch.collection_agent, "run", side_effect=mock_collection),
            patch.object(orch.analysis_agent, "run", side_effect=mock_analysis),
            patch.object(
                orch.expression_agent, "run", new_callable=AsyncMock
            ) as me,
        ):
            me.return_value = _mock_expression_result("⚠️ WARNING")

            state = V8State(
                user_input="全面检查光纤1",
                trace_id="t2",
                execution_plan=ExecutionPlan(max_loop_rounds=3),
            )
            result = await orch.execute(state)

            assert result.loop_context.round == 2
            assert result.final_status == "WARNING"

    @pytest.mark.asyncio
    async def test_no_plan_error(self):
        """无执行计划 → 错误."""
        orch = Orchestrator()
        state = V8State(user_input="test", trace_id="t3")
        result = await orch.execute(state)
        assert result.final_status == "ERROR"

    @pytest.mark.asyncio
    async def test_collection_failure(self):
        """Collection 失败 → 终止."""
        orch = Orchestrator()

        with (
            patch.object(
                orch.collection_agent, "run", new_callable=AsyncMock
            ) as mc,
            patch.object(
                orch.expression_agent, "run", new_callable=AsyncMock
            ) as me,
        ):
            mc.return_value = AgentResult(
                layer=AgentLayer.COLLECTION, success=False, error="timeout"
            )
            me.return_value = _mock_expression_result("❌ 数据采集失败")

            state = V8State(
                user_input="test",
                trace_id="t4",
                execution_plan=ExecutionPlan(),
            )
            result = await orch.execute(state)
            assert result.loop_context.terminated_reason == "collection_error"
