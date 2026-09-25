"""
带 mock 后端的工具集成测试 [v7.1]。

验证全部 23+ 个工具是否正确：
- 构造 API 路径
- 传递参数
- 解析响应
- 处理错误

所有 C++ 后端调用均由 mock_backend fixture 拦截。
"""

import json

import pytest

from src.tools.alarm_tools import alarm_query
from src.tools.colored_tools import all_colored_fibers_query, colored_fibers_query
from src.tools.performance_tools import (
    fiber_performance_query,
    fiber_spanloss_query,
)
from src.tools.stats_tools import fiber_stats_query, fiber_trend_query
from src.tools.topology_tools import (
    batch_fiber_connection_query,
    board_query,
    fiber_connection_query,
    fiber_scene_query,
)


class TestTopologyToolsIntegration:
    """拓扑工具 → mock 后端集成。"""

    @pytest.mark.asyncio
    async def test_fiber_connection_full_response(self, mock_backend):
        """验证完整的拓扑响应结构。"""
        result = await fiber_connection_query.ainvoke({"fiber_id": "FIB-0001"})
        data = json.loads(result)
        assert data["fiber_id"] == 1
        assert data["src_board"]["board_type"] == "OLP"
        assert data["dst_board"]["ne_name"] == "NE-West-01"
        assert data["fiber_length_km"] == 42.5

    @pytest.mark.asyncio
    async def test_fiber_scene_includes_internal(self, mock_backend):
        """场景查询包含内部光纤与无源盘。"""
        result = await fiber_scene_query.ainvoke({"fiber_id": "FIB-0001"})
        data = json.loads(result)
        assert "internal_fibers" in data
        assert "passive_boards" in data
        assert len(data["internal_fibers"]) > 0

    @pytest.mark.asyncio
    async def test_batch_query_mixed_results(self, mock_backend):
        """批量查询处理已找到 + 未找到的光纤。"""
        result = await batch_fiber_connection_query.ainvoke(
            {
                "fiber_ids": ["1", "2", "999"],
                "chunk_id": "test-chunk",
            }
        )
        data = json.loads(result)
        assert data["found_count"] == 2
        # 检查未找到的条目
        not_found = [r for r in data["results"] if not r["found"]]
        assert len(not_found) == 1
        assert not_found[0]["fiber_id"] == 999

    @pytest.mark.asyncio
    async def test_board_query_ports(self, mock_backend):
        """盘查询返回端口详情。"""
        result = await board_query.ainvoke({"board_id": "1"})
        data = json.loads(result)
        assert len(data["ports"]) == 3
        assert data["ports"][0]["status"] == "active"


class TestPerformanceToolsIntegration:
    """性能工具 → mock 后端集成。"""

    @pytest.mark.asyncio
    async def test_spanloss_values(self, mock_backend):
        """跨段损耗查询返回正确的测量值。"""
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["spanloss"] == 3.2
        assert data["unit"] == "dB"

    @pytest.mark.asyncio
    async def test_performance_full_metrics(self, mock_backend):
        """性能查询返回 OOP/IOP/SNR。"""
        result = await fiber_performance_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["oop"] == -3.5
        assert data["iop"] == -10.2
        assert "snr" in data


class TestAlarmToolsIntegration:
    """告警工具 → mock 后端集成。"""

    @pytest.mark.asyncio
    async def test_alarm_structure(self, mock_backend):
        """告警响应具有正确的结构。"""
        result = await alarm_query.ainvoke({})
        data = json.loads(result)
        assert data["total"] == 2
        alarm = data["alarms"][0]
        assert "alarm_type" in alarm
        assert "alarm_level" in alarm
        assert "raised_at" in alarm
        assert alarm["alarm_type"] == "LOS"


class TestColoredToolsIntegration:
    """颜色光纤工具 → mock 后端集成。"""

    @pytest.mark.asyncio
    async def test_colored_red_fibers(self, mock_backend):
        """红色光纤查询返回正确的光纤。"""
        result = await colored_fibers_query.ainvoke({"color": "RED"})
        data = json.loads(result)
        assert data["total"] == 3
        for fiber in data["fibers"]:
            assert fiber["color"] == "RED"
            assert fiber["spanloss"] > 8.0  # 所有红色光纤的跨段损耗都很高

    @pytest.mark.asyncio
    async def test_all_colored_grouped(self, mock_backend):
        """全部颜色查询按颜色分组。"""
        result = await all_colored_fibers_query.ainvoke({})
        data = json.loads(result)
        assert len(data["red"]) == 3
        assert len(data["yellow"]) == 8
        assert data["green_count"] == 109


class TestStatsToolsIntegration:
    """统计工具 → mock 后端集成。"""

    @pytest.mark.asyncio
    async def test_realtime_stats_consistency(self, mock_backend):
        """统计数据应内部一致。"""
        result = await fiber_stats_query.ainvoke({})
        data = json.loads(result)
        total = data["total_fibers"]
        color_sum = data["red_count"] + data["yellow_count"] + data["green_count"]
        assert total == color_sum == 120

    @pytest.mark.asyncio
    async def test_trend_data_points(self, mock_backend):
        """趋势数据有 7 个每日数据点。"""
        result = await fiber_trend_query.ainvoke({})
        data = json.loads(result)
        assert len(data["points"]) == 7
        # 验证红色数量单调不减
        red_counts = [p["red_count"] for p in data["points"]]
        assert all(red_counts[i] <= red_counts[i + 1] for i in range(len(red_counts) - 1))


class TestCustomMockResponses:
    """测试注入自定义 mock 响应。"""

    @pytest.mark.asyncio
    async def test_inject_custom_spanloss(self, mock_backend):
        """为特定光纤注入自定义响应。"""
        mock_backend["/api/v1/fibers/50/spanloss"] = json.dumps(
            {
                "fiber_id": 50,
                "spanloss": 7.7,
                "unit": "dB",
                "status": "warning",
            }
        )
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "50"})
        data = json.loads(result)
        assert data["spanloss"] == 7.7

    @pytest.mark.asyncio
    async def test_inject_backend_error(self, mock_backend):
        """注入后端错误响应。"""
        mock_backend["/api/v1/fibers/0/spanloss"] = json.dumps(
            {
                "error": True,
                "message": "Invalid fiber ID: must be positive",
            }
        )
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "0"})
        data = json.loads(result)
        assert data["error"] is True

    @pytest.mark.asyncio
    async def test_override_default_mock(self, mock_backend):
        """覆盖默认 mock 响应。"""
        # 覆盖光纤 1 的跨段损耗
        mock_backend["/api/v1/fibers/1/spanloss"] = json.dumps(
            {
                "fiber_id": 1,
                "spanloss": 99.9,
                "unit": "dB",
                "status": "critical",
            }
        )
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["spanloss"] == 99.9  # 已被覆盖的值
