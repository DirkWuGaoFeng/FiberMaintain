"""Collection Agent 单元测试."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.v8.agents.collection_agent import CollectionAgent
from src.v8.contracts import CollectionPayload
from src.v8.models import AgentLayer, ExecutionPlan


class TestCollectionAgent:
    def test_layer(self):
        agent = CollectionAgent()
        assert agent.layer == AgentLayer.COLLECTION

    def test_resolve_tools_valid(self):
        agent = CollectionAgent()
        tools = agent._resolve_tools(["fiber_spanloss_query", "alarm_query"])
        assert len(tools) == 2

    def test_resolve_tools_unknown(self):
        agent = CollectionAgent()
        tools = agent._resolve_tools(["nonexistent_tool"])
        assert len(tools) == 0

    def test_build_prompt_basic(self):
        agent = CollectionAgent()
        plan = ExecutionPlan(tools=["fiber_spanloss_query"])
        ctx = {"user_input": "查看光纤1", "normalized_params": {"fiber_ids": [1]}}
        prompt = agent._build_prompt(plan, ctx)
        assert "查看光纤1" in prompt
        assert "fiber_ids" in prompt

    def test_build_prompt_with_additional_query(self):
        agent = CollectionAgent()
        plan = ExecutionPlan()
        ctx = {
            "user_input": "查看光纤1",
            "additional_query": {"reason": "缺少告警数据", "tool": "alarm_query"},
            "loop_round": 2,
        }
        prompt = agent._build_prompt(plan, ctx)
        assert "补充采集" in prompt
        assert "alarm_query" in prompt


class TestDeterministicPath:
    """确定性采集路径测试."""

    def test_can_use_deterministic_true(self):
        agent = CollectionAgent()
        plan = ExecutionPlan(
            match_type="rule",
            tools=["fiber_spanloss_query", "fiber_performance_query"],
        )
        ctx = {"normalized_params": {"fiber_ids": [1]}}
        assert agent._can_use_deterministic(plan, ctx) is True

    def test_can_use_deterministic_false_llm_match(self):
        agent = CollectionAgent()
        plan = ExecutionPlan(match_type="llm", tools=["fiber_spanloss_query"])
        ctx = {"normalized_params": {"fiber_ids": [1]}}
        assert agent._can_use_deterministic(plan, ctx) is False

    def test_can_use_deterministic_false_no_fiber_ids(self):
        agent = CollectionAgent()
        plan = ExecutionPlan(match_type="rule", tools=["fiber_spanloss_query"])
        ctx = {"normalized_params": {}}
        assert agent._can_use_deterministic(plan, ctx) is False

    def test_can_use_deterministic_false_additional_query(self):
        agent = CollectionAgent()
        plan = ExecutionPlan(match_type="rule", tools=["fiber_spanloss_query"])
        ctx = {
            "normalized_params": {"fiber_ids": [1]},
            "additional_query": {"reason": "need more"},
        }
        assert agent._can_use_deterministic(plan, ctx) is False

    @pytest.mark.asyncio
    async def test_deterministic_collect_success(self):
        """确定性路径：直调 API 返回结构化数据."""
        agent = CollectionAgent()
        plan = ExecutionPlan(
            match_type="rule",
            tools=["fiber_spanloss_query", "fiber_performance_query"],
        )
        ctx = {
            "trace_id": "t1",
            "normalized_params": {"fiber_ids": [1]},
        }

        # Mock 工具调用
        spanloss_response = json.dumps({"fiber_id": 1, "spanloss": 3.5})
        perf_response = json.dumps(
            {"fiber_id": 1, "src_oop": -5.2, "dst_iop": -8.1}
        )

        async def mock_ainvoke(params):
            if "spanloss" in str(params):
                return spanloss_response
            return perf_response

        with patch(
            "src.v8.agents.collection_agent._TOOL_MAP"
        ) as mock_map:
            mock_tool_spanloss = AsyncMock()
            mock_tool_spanloss.ainvoke = AsyncMock(
                return_value=spanloss_response
            )
            mock_tool_perf = AsyncMock()
            mock_tool_perf.ainvoke = AsyncMock(return_value=perf_response)
            mock_map.get = lambda name: {
                "fiber_spanloss_query": mock_tool_spanloss,
                "fiber_performance_query": mock_tool_perf,
            }.get(name)

            result = await agent.execute(plan, ctx)

        assert result.success
        assert result.llm_calls == 0  # 零 LLM
        payload = CollectionPayload.model_validate(result.data)
        assert payload.collection_mode == "deterministic"
        assert len(payload.metrics) == 1
        assert payload.metrics[0].spanloss_db == 3.5
        assert payload.metrics[0].oop_dbm == -5.2
        assert payload.metrics[0].iop_dbm == -8.1

    @pytest.mark.asyncio
    async def test_deterministic_collect_tool_failure(self):
        """确定性路径：工具失败不崩溃，记录错误."""
        agent = CollectionAgent()
        plan = ExecutionPlan(
            match_type="rule",
            tools=["fiber_spanloss_query"],
        )
        ctx = {
            "trace_id": "t1",
            "normalized_params": {"fiber_ids": [1]},
        }

        with patch(
            "src.v8.agents.collection_agent._TOOL_MAP"
        ) as mock_map:
            mock_tool = AsyncMock()
            mock_tool.ainvoke = AsyncMock(
                side_effect=ConnectionError("backend down")
            )
            mock_map.get = lambda name: mock_tool

            result = await agent.execute(plan, ctx)

        # 不崩溃，但工具调用记录失败
        assert result.success  # Agent 本身成功（降级）
        payload = CollectionPayload.model_validate(result.data)
        assert payload.tool_calls[0].success is False
        assert "backend down" in payload.tool_calls[0].error

    def test_parse_tool_response_spanloss(self):
        agent = CollectionAgent()
        from src.v8.contracts import FiberMetrics

        m = FiberMetrics(fiber_id=1)
        agent._parse_tool_response(
            "fiber_spanloss_query",
            json.dumps({"fiber_id": 1, "spanloss": 4.2}),
            m,
        )
        assert m.spanloss_db == 4.2

    def test_parse_tool_response_performance(self):
        agent = CollectionAgent()
        from src.v8.contracts import FiberMetrics

        m = FiberMetrics(fiber_id=1)
        agent._parse_tool_response(
            "fiber_performance_query",
            json.dumps({"fiber_id": 1, "src_oop": -3.0, "dst_iop": -6.5}),
            m,
        )
        assert m.oop_dbm == -3.0
        assert m.iop_dbm == -6.5

    def test_parse_tool_response_invalid_json(self):
        agent = CollectionAgent()
        from src.v8.contracts import FiberMetrics

        m = FiberMetrics(fiber_id=1)
        agent._parse_tool_response("fiber_spanloss_query", "not json", m)
        assert m.spanloss_db is None  # 不崩溃，字段保持 None
