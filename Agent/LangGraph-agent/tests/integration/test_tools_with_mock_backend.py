"""
Integration tests for Tools with Mock Backend [v7.1].

Verifies all 23+ tools correctly:
- Construct API paths
- Pass parameters
- Parse responses
- Handle errors

All C++ backend calls are intercepted by mock_backend fixture.
"""

import json

import pytest

from src.tools.topology_tools import (
    board_query,
    batch_board_query,
    batch_fiber_connection_query,
    fiber_connection_query,
    fiber_scene_query,
)
from src.tools.performance_tools import (
    fiber_performance_query,
    fiber_spanloss_query,
)
from src.tools.alarm_tools import alarm_query
from src.tools.colored_tools import colored_fibers_query, all_colored_fibers_query
from src.tools.stats_tools import fiber_stats_query, fiber_trend_query


class TestTopologyToolsIntegration:
    """Topology tools → mock backend integration."""

    @pytest.mark.asyncio
    async def test_fiber_connection_full_response(self, mock_backend):
        """Verify full topology response structure."""
        result = await fiber_connection_query.ainvoke({"fiber_id": "FIB-0001"})
        data = json.loads(result)
        assert data["fiber_id"] == 1
        assert data["src_board"]["board_type"] == "OLP"
        assert data["dst_board"]["ne_name"] == "NE-West-01"
        assert data["fiber_length_km"] == 42.5

    @pytest.mark.asyncio
    async def test_fiber_scene_includes_internal(self, mock_backend):
        """Scene query includes internal fibers and passive boards."""
        result = await fiber_scene_query.ainvoke({"fiber_id": "FIB-0001"})
        data = json.loads(result)
        assert "internal_fibers" in data
        assert "passive_boards" in data
        assert len(data["internal_fibers"]) > 0

    @pytest.mark.asyncio
    async def test_batch_query_mixed_results(self, mock_backend):
        """Batch query handles found + not-found fibers."""
        result = await batch_fiber_connection_query.ainvoke({
            "fiber_ids": ["1", "2", "999"],
            "chunk_id": "test-chunk",
        })
        data = json.loads(result)
        assert data["found_count"] == 2
        # Check not-found entry
        not_found = [r for r in data["results"] if not r["found"]]
        assert len(not_found) == 1
        assert not_found[0]["fiber_id"] == 999

    @pytest.mark.asyncio
    async def test_board_query_ports(self, mock_backend):
        """Board query returns port details."""
        result = await board_query.ainvoke({"board_id": "1"})
        data = json.loads(result)
        assert len(data["ports"]) == 3
        assert data["ports"][0]["status"] == "active"


class TestPerformanceToolsIntegration:
    """Performance tools → mock backend integration."""

    @pytest.mark.asyncio
    async def test_spanloss_values(self, mock_backend):
        """Spanloss query returns correct measurement."""
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["spanloss"] == 3.2
        assert data["unit"] == "dB"

    @pytest.mark.asyncio
    async def test_performance_full_metrics(self, mock_backend):
        """Performance query returns OOP/IOP/SNR."""
        result = await fiber_performance_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["oop"] == -3.5
        assert data["iop"] == -10.2
        assert "snr" in data


class TestAlarmToolsIntegration:
    """Alarm tools → mock backend integration."""

    @pytest.mark.asyncio
    async def test_alarm_structure(self, mock_backend):
        """Alarm response has correct structure."""
        result = await alarm_query.ainvoke({})
        data = json.loads(result)
        assert data["total"] == 2
        alarm = data["alarms"][0]
        assert "alarm_type" in alarm
        assert "alarm_level" in alarm
        assert "raised_at" in alarm
        assert alarm["alarm_type"] == "LOS"


class TestColoredToolsIntegration:
    """Colored fiber tools → mock backend integration."""

    @pytest.mark.asyncio
    async def test_colored_red_fibers(self, mock_backend):
        """Red fiber query returns correct fibers."""
        result = await colored_fibers_query.ainvoke({"color": "RED"})
        data = json.loads(result)
        assert data["total"] == 3
        for fiber in data["fibers"]:
            assert fiber["color"] == "RED"
            assert fiber["spanloss"] > 8.0  # All red fibers have high spanloss

    @pytest.mark.asyncio
    async def test_all_colored_grouped(self, mock_backend):
        """All colored query groups by color."""
        result = await all_colored_fibers_query.ainvoke({})
        data = json.loads(result)
        assert len(data["red"]) == 3
        assert len(data["yellow"]) == 8
        assert data["green_count"] == 109


class TestStatsToolsIntegration:
    """Stats tools → mock backend integration."""

    @pytest.mark.asyncio
    async def test_realtime_stats_consistency(self, mock_backend):
        """Stats numbers should be internally consistent."""
        result = await fiber_stats_query.ainvoke({})
        data = json.loads(result)
        total = data["total_fibers"]
        color_sum = data["red_count"] + data["yellow_count"] + data["green_count"]
        assert total == color_sum == 120

    @pytest.mark.asyncio
    async def test_trend_data_points(self, mock_backend):
        """Trend data has 7 daily points."""
        result = await fiber_trend_query.ainvoke({})
        data = json.loads(result)
        assert len(data["points"]) == 7
        # Verify monotonically non-decreasing red count
        red_counts = [p["red_count"] for p in data["points"]]
        assert all(red_counts[i] <= red_counts[i+1] for i in range(len(red_counts)-1))


class TestCustomMockResponses:
    """Test injecting custom mock responses."""

    @pytest.mark.asyncio
    async def test_inject_custom_spanloss(self, mock_backend):
        """Inject custom response for specific fiber."""
        mock_backend["/api/v1/fibers/50/spanloss"] = json.dumps({
            "fiber_id": 50,
            "spanloss": 7.7,
            "unit": "dB",
            "status": "warning",
        })
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "50"})
        data = json.loads(result)
        assert data["spanloss"] == 7.7

    @pytest.mark.asyncio
    async def test_inject_backend_error(self, mock_backend):
        """Inject backend error response."""
        mock_backend["/api/v1/fibers/0/spanloss"] = json.dumps({
            "error": True,
            "message": "Invalid fiber ID: must be positive",
        })
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "0"})
        data = json.loads(result)
        assert data["error"] is True

    @pytest.mark.asyncio
    async def test_override_default_mock(self, mock_backend):
        """Override a default mock response."""
        # Override fiber 1 spanloss
        mock_backend["/api/v1/fibers/1/spanloss"] = json.dumps({
            "fiber_id": 1,
            "spanloss": 99.9,
            "unit": "dB",
            "status": "critical",
        })
        result = await fiber_spanloss_query.ainvoke({"fiber_id": "1"})
        data = json.loads(result)
        assert data["spanloss"] == 99.9  # Overridden value
