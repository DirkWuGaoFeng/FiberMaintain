"""
SLA 契约测试 — 降级路径不变量验证.

核心不变量：
1. success=False 时 error 必须非空
2. success=False 时 data 不能是空 dict（必须有降级数据）
3. latency_ms 必须 >= 0
4. layer 必须与 Agent 声明一致

遍历所有故障模式，断言契约不变量。
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.v8.agents.analysis_agent import AnalysisAgent
from src.v8.agents.collection_agent import CollectionAgent
from src.v8.agents.expression_agent import ExpressionAgent
from src.v8.models import AgentLayer, AgentResult, ExecutionPlan
from src.v8.resilience import reset_llm_breaker


# =============================================================================
# 契约断言工具
# =============================================================================


def assert_sla_contract(result: AgentResult, expected_layer: AgentLayer):
    """验证 AgentResult 满足 SLA 契约."""
    # 不变量 1: layer 一致
    assert result.layer == expected_layer, (
        f"Layer mismatch: expected {expected_layer}, got {result.layer}"
    )

    # 不变量 2: latency 非负
    assert result.latency_ms >= 0, f"Negative latency: {result.latency_ms}"

    # 不变量 3: 失败时 error 非空
    if not result.success:
        assert result.error, (
            f"SLA violation: success=False but error is empty "
            f"(layer={result.layer})"
        )

    # 不变量 4: 失败时 data 不能是空 dict（有损但可用）
    if not result.success:
        assert result.data, (
            f"SLA violation: success=False but data is empty "
            f"(layer={result.layer}, error={result.error})"
        )


# =============================================================================
# Collection Agent 故障模式
# =============================================================================


class TestCollectionSLA:
    @pytest.fixture(autouse=True)
    def setup(self):
        reset_llm_breaker()
        yield
        reset_llm_breaker()

    @pytest.mark.asyncio
    async def test_all_tools_fail(self):
        """所有工具调用失败 → 有损但可用."""
        agent = CollectionAgent()
        plan = ExecutionPlan(
            match_type="rule",
            tools=["fiber_spanloss_query"],
        )
        ctx = {
            "trace_id": "sla-test",
            "normalized_params": {"fiber_ids": [1]},
        }

        with patch("src.v8.agents.collection_agent._TOOL_MAP") as mock_map:
            mock_tool = AsyncMock()
            mock_tool.ainvoke = AsyncMock(
                side_effect=ConnectionError("backend unreachable")
            )
            mock_map.get = lambda name: mock_tool
            result = await agent.execute(plan, ctx)

        # 确定性路径：工具失败不崩溃，payload 仍有 tool_calls 记录
        assert result.success  # Agent 本身成功（降级记录）
        assert result.data  # 有数据
        assert result.data.get("tool_calls")  # 有调用记录

    @pytest.mark.asyncio
    async def test_timeout_degradation(self):
        """超时 → SLA 契约满足."""
        agent = CollectionAgent()
        plan = ExecutionPlan(match_type="rule", tools=["fiber_spanloss_query"])
        ctx = {
            "trace_id": "sla-test",
            "normalized_params": {"fiber_ids": [1]},
            "execution_mode": "deterministic",
        }

        # 模拟极慢工具
        async def slow_invoke(params):
            await asyncio.sleep(100)
            return "{}"

        with patch("src.v8.agents.collection_agent._TOOL_MAP") as mock_map:
            mock_tool = AsyncMock()
            mock_tool.ainvoke = slow_invoke
            mock_map.get = lambda name: mock_tool
            result = await agent.run(plan, ctx)  # 通过 run() 触发超时

        assert_sla_contract(result, AgentLayer.COLLECTION)
        assert not result.success
        assert "超时" in result.error


# =============================================================================
# Analysis Agent 故障模式
# =============================================================================


class TestAnalysisSLA:
    @pytest.fixture(autouse=True)
    def setup(self):
        reset_llm_breaker()
        yield
        reset_llm_breaker()

    @pytest.mark.asyncio
    async def test_llm_failure_degradation(self):
        """LLM 分析失败 → 有损但可用."""
        agent = AnalysisAgent()
        plan = ExecutionPlan(analysis_mode="llm_only")
        ctx = {
            "trace_id": "sla-test",
            "collection_data": {
                "metrics": [{"fiber_id": 1, "spanloss_db": 3.0}],
            },
            "user_input": "分析光纤1",
        }

        with patch(
            "src.llm.provider.get_analysis_llm",
            side_effect=RuntimeError("Ollama not running"),
        ):
            result = await agent.execute(plan, ctx)

        assert_sla_contract(result, AgentLayer.ANALYSIS)
        assert not result.success
        # 降级数据：verdict 仍然存在
        assert "verdict" in result.data
        assert result.data["verdict"]["status"] == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_empty_collection_data(self):
        """空采集数据 → 不崩溃."""
        agent = AnalysisAgent()
        plan = ExecutionPlan(analysis_mode="rule_first")
        ctx = {
            "trace_id": "sla-test",
            "collection_data": {},
            "user_input": "分析",
        }

        with patch(
            "src.llm.provider.get_analysis_llm",
            side_effect=RuntimeError("no LLM"),
        ):
            result = await agent.execute(plan, ctx)

        # 规则路径返回 UNKNOWN，然后 LLM 失败 → 降级
        assert result.data  # 有数据


# =============================================================================
# Expression Agent 故障模式
# =============================================================================


class TestExpressionSLA:
    @pytest.mark.asyncio
    async def test_empty_verdict(self):
        """空 verdict → 不崩溃，输出兜底文本."""
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {"analysis_data": {}}

        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data.get("response")  # 有输出文本

    @pytest.mark.asyncio
    async def test_malformed_verdict(self):
        """畸形 verdict → 不崩溃."""
        agent = ExpressionAgent()
        plan = ExecutionPlan(output_format="narrative")
        ctx = {
            "analysis_data": {
                "verdict": {"status": "WEIRD_STATUS", "findings": None}
            }
        }

        result = await agent.execute(plan, ctx)
        assert result.success
        assert result.data.get("response")


# =============================================================================
# 全链路故障注入
# =============================================================================


class TestFullChainSLA:
    """验证 Orchestrator 在任何单点故障下都返回有损但可用的结果."""

    @pytest.fixture(autouse=True)
    def setup(self):
        reset_llm_breaker()
        yield
        reset_llm_breaker()

    @pytest.mark.asyncio
    async def test_collection_total_failure(self):
        """Collection 完全失败 → Orchestrator 仍返回结果."""
        from src.v8.models import V8State
        from src.v8.orchestrator import Orchestrator

        orch = Orchestrator()
        plan = ExecutionPlan(
            scenario_id="test",
            intent="spanloss_check",
            tools=["fiber_spanloss_query"],
        )
        state = V8State(
            user_input="查看光纤1",
            trace_id="sla-chain",
            execution_plan=plan,
            normalized_params={"fiber_ids": [1]},
        )

        with patch.object(
            orch.collection_agent,
            "run",
            new_callable=AsyncMock,
            return_value=AgentResult(
                layer=AgentLayer.COLLECTION,
                success=False,
                error="total failure",
                data={"fallback": True},
            ),
        ):
            result = await orch.execute(state)

        # Orchestrator 不应崩溃
        assert result.final_response  # 有输出
        assert result.final_status  # 有状态
