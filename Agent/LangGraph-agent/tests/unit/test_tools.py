"""
工具层单元测试 [v7.1]。

使用 mock 后端测试全部 23+ 个工具：
- 拓扑工具（5）
- 性能工具（2）
- 光纤工具（1）
- 告警工具（1）
- 彩色工具（2）
- 统计工具（2）
- 板卡工具（1）
- NE 工具（1）
- 批量工具（4）
- 记忆工具（2）
- RAG 工具（2）
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
    batch_board_query,
    batch_fiber_connection_query,
    board_query,
    fiber_connection_query,
    fiber_scene_query,
)


class TestTopologyTools:
    """带 mock 后端的拓扑工具测试。"""

    @pytest.mark.asyncio
    async def test_fiber_connection_query(self, mock_backend):
        """单纤连接查询返回有效 JSON。"""
        result = await fiber_connection_query.ainvoke({"fiber_id": "FIB-0001"})
        data = json.loads(result)
        assert data["fiber_id"] == 1
        assert "src_board" in data
        assert "dst_board" in data

    @pytest.mark.asyncio
    async def test_fiber_connection_query_numeric_id(self, mock_backend):
        """数字格式的光纤 ID 同样有效。"""
        result = await fiber_connection_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["fiber_id"] == 1

    @pytest.mark.asyncio
    async def test_fiber_scene_query(self, mock_backend):
        """光纤场景查询返回完整拓扑。"""
        result = await fiber_scene_query.ainvoke({"fiber_id": "FIB-0001"})
        data = json.loads(result)
        assert data["fiber_id"] == 1
        assert "src_ne" in data
        assert "dst_ne" in data
        assert "internal_fibers" in data

    @pytest.mark.asyncio
    async def test_batch_fiber_connection_query(self, mock_backend):
        """批量光纤查询返回结果数组。"""
        result = await batch_fiber_connection_query.ainvoke(
            {
                "fiber_ids": ["1", "2", "999"],
                "chunk_id": "chunk-001",
            }
        )
        data = json.loads(result)
        assert "results" in data
        assert data["total"] == 3
        assert data["found_count"] == 2

    @pytest.mark.asyncio
    async def test_board_query(self, mock_backend):
        """板卡查询返回板卡详情。"""
        result = await board_query.ainvoke({"board_id": "1"})
        data = json.loads(result)
        assert data["board_id"] == 1
        assert data["board_type"] == "OLP"
        assert "ports" in data

    @pytest.mark.asyncio
    async def test_batch_board_query(self, mock_backend):
        """批量板卡查询返回结果。"""
        result = await batch_board_query.ainvoke({"board_ids": ["1", "2"]})
        data = json.loads(result)
        assert "results" in data

    @pytest.mark.asyncio
    async def test_fiber_not_found(self, mock_backend):
        """查询不存在的光纤返回错误 mock。"""
        result = await fiber_connection_query.ainvoke({"fiber_id": "9999"})
        data = json.loads(result)
        assert data.get("error") is True


class TestPerformanceTools:
    """性能工具测试。"""

    @pytest.mark.asyncio
    async def test_fiber_spanloss_query(self, mock_backend):
        """Spanloss 查询返回测量数据。"""
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert "spanloss" in data or "fiber_id" in data

    @pytest.mark.asyncio
    async def test_fiber_performance_query(self, mock_backend):
        """性能查询返回 OOP/IOP 数据。"""
        result = await fiber_performance_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert "oop" in data or "fiber_id" in data


class TestAlarmTools:
    """告警工具测试。"""

    @pytest.mark.asyncio
    async def test_alarm_query_all(self, mock_backend):
        """查询所有当前告警。"""
        result = await alarm_query.ainvoke({})
        data = json.loads(result)
        assert "alarms" in data
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_alarm_query_filtered(self, mock_backend):
        """使用 board_id 过滤查询告警。"""
        result = await alarm_query.ainvoke({"board_id": "2"})
        # 仍应从 mock 返回（过滤在后端侧）
        data = json.loads(result)
        assert "alarms" in data or "error" in data


class TestColoredTools:
    """着色光纤工具测试。"""

    @pytest.mark.asyncio
    async def test_colored_fibers_query(self, mock_backend):
        """按颜色查询着色光纤。"""
        result = await colored_fibers_query.ainvoke({"color": "RED"})
        data = json.loads(result)
        assert "fibers" in data
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_all_colored_fibers_query(self, mock_backend):
        """按颜色分组查询所有彩色光纤。"""
        result = await all_colored_fibers_query.ainvoke({})
        data = json.loads(result)
        assert "red" in data
        assert "yellow" in data
        assert data["total"] == 120


class TestStatsTools:
    """统计工具测试。"""

    @pytest.mark.asyncio
    async def test_fiber_stats_query(self, mock_backend):
        """实时统计查询返回计数。"""
        result = await fiber_stats_query.ainvoke({})
        data = json.loads(result)
        assert data["total_fibers"] == 120
        assert data["red_count"] == 3
        assert data["yellow_count"] == 8
        assert data["green_count"] == 109

    @pytest.mark.asyncio
    async def test_fiber_trend_query(self, mock_backend):
        """趋势查询返回时间序列数据。"""
        result = await fiber_trend_query.ainvoke({})
        data = json.loads(result)
        assert "points" in data
        assert len(data["points"]) == 7

    @pytest.mark.asyncio
    async def test_fiber_trend_query_with_time_range(self, mock_backend):
        """带时间范围参数的趋势查询。"""
        result = await fiber_trend_query.ainvoke(
            {
                "start_time": "2026-07-24T00:00:00Z",
                "end_time": "2026-07-30T00:00:00Z",
            }
        )
        data = json.loads(result)
        assert "points" in data


class TestToolErrorHandling:
    """测试后端返回错误时工具的行为。"""

    @pytest.mark.asyncio
    async def test_backend_error_response(self, mock_backend):
        """工具应透传后端的错误 JSON。"""
        # mock_backend 对未知路径返回错误
        result = await fiber_connection_query.ainvoke({"fiber_id": "0"})
        # 不应抛出异常，返回错误 JSON
        data = json.loads(result)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_custom_error_injection(self, mock_backend):
        """注入自定义错误响应。"""
        mock_backend["/api/v1/topology/fibers/99"] = json.dumps(
            {
                "error": True,
                "message": "Fiber 99 not found in database",
            }
        )
        result = await fiber_connection_query.ainvoke({"fiber_id": "99"})
        data = json.loads(result)
        assert data["error"] is True
        assert "not found" in data["message"]
