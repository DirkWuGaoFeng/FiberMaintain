"""
主图集成测试 — 快速路径 [v7.1]。

测试完整快速路径链路：
  input_guard → rule_engine → fast_path_executor → result_aggregator

所有后端调用均为 mock。快速路径中无 LLM 调用。
"""

import json

import pytest

from src.graph.state import create_initial_state
from src.nodes.fast_path_executor import fast_path_executor_node
from src.nodes.input_guard import input_guard_node
from src.nodes.rule_engine import rule_engine_node


class TestFastPathSpanloss:
    """快速路径：单纤跨段损耗查询。"""

    @pytest.mark.asyncio
    async def test_spanloss_normal(self, mock_backend):
        """查询光纤1的衰耗 → Fast Path → normal result."""
        state = create_initial_state("查询光纤1的衰耗")

        # 第 1 步：input_guard
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        assert state.get("processing_path") != "blocked"

        # 第 2 步：rule_engine
        rule_result = await rule_engine_node(state)
        state.update(rule_result)
        assert state["rule_match"] is not None
        assert state["rule_match"]["intent"] == "spanloss_query"
        assert state["rule_match"]["fast_path_eligible"] is True

        # 第 3 步：fast_path_executor
        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert state["processing_path"] == "fast"
        assert state["final_output"] is not None
        assert "3.2" in state["final_output"]  # mock 中的 spanloss 值

    @pytest.mark.asyncio
    async def test_spanloss_warning(self, mock_backend):
        """查询光纤2的衰耗 → spanloss=6.5 → warning status."""
        state = create_initial_state("查询光纤2的衰耗")
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        rule_result = await rule_engine_node(state)
        state.update(rule_result)

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert "6.5" in state["final_output"]
        assert state["processing_path"] == "fast"

    @pytest.mark.asyncio
    async def test_spanloss_critical(self, mock_backend):
        """查询光纤3的衰耗 → spanloss=9.2 → critical status."""
        state = create_initial_state("查询光纤3的衰耗")
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        rule_result = await rule_engine_node(state)
        state.update(rule_result)

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert "9.2" in state["final_output"]


class TestFastPathConnection:
    """快速路径：光纤连纤查询。"""

    @pytest.mark.asyncio
    async def test_connection_query(self, mock_backend):
        """查询光纤1的连纤 → returns topology data."""
        state = create_initial_state("查询光纤1的连纤")
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        rule_result = await rule_engine_node(state)
        state.update(rule_result)
        assert state["rule_match"]["intent"] == "connection_query"

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert state["processing_path"] == "fast"
        assert state["final_output"] is not None


class TestFastPathColored:
    """快速路径：带颜色的光纤查询。"""

    @pytest.mark.asyncio
    async def test_red_fiber_query(self, mock_backend):
        """有哪些红色光纤 → colored query fast path."""
        state = create_initial_state("有哪些红色光纤")
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        rule_result = await rule_engine_node(state)
        state.update(rule_result)
        assert state["rule_match"]["intent"] == "colored_query"
        assert state["rule_match"]["params"]["color"] == "RED"

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert state["processing_path"] == "fast"


class TestFastPathStats:
    """快速路径：统计查询。"""

    @pytest.mark.asyncio
    async def test_stats_query(self, mock_backend):
        """光纤总数有多少 → stats fast path."""
        state = create_initial_state("光纤总数有多少")
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        rule_result = await rule_engine_node(state)
        state.update(rule_result)
        assert state["rule_match"]["intent"] == "stats_query"

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert state["processing_path"] == "fast"
        assert state["final_output"] is not None


class TestFastPathPortAlarm:
    """快速路径：端口告警查询。"""

    @pytest.mark.asyncio
    async def test_port_alarm_query(self, mock_backend):
        """2号盘3号口的告警 → port alarm fast path."""
        state = create_initial_state("2号盘3号口的告警")
        guard_result = await input_guard_node(state)
        state.update(guard_result)
        rule_result = await rule_engine_node(state)
        state.update(rule_result)
        assert state["rule_match"]["intent"] == "port_alarm_query"
        assert state["rule_match"]["params"]["board_id"] == 2
        assert state["rule_match"]["params"]["port_id"] == 3

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        assert state["processing_path"] == "fast"


class TestFastPathErrorHandling:
    """快速路径错误场景。"""

    @pytest.mark.asyncio
    async def test_backend_error_graceful(self, mock_backend):
        """后端返回错误时应产生降级输出。"""
        # 覆盖 mock 以返回错误
        mock_backend["/api/v1/fibers/99/spanloss"] = json.dumps({"error": True, "message": "Fiber not found"})
        state = create_initial_state("查询光纤99的衰耗")
        # 手动为光纤 99 设置 rule_match
        state["rule_match"] = {
            "intent": "spanloss_query",
            "params": {"fiber_id": 99},
            "confidence": 1.0,
            "template_id": "T_SPANLOSS",
            "fast_path_eligible": True,
        }
        state["intent"] = "spanloss_query"

        fp_result = await fast_path_executor_node(state)
        state.update(fp_result)
        # 仍应产生输出（错误消息或降级）
        assert state["final_output"] is not None
