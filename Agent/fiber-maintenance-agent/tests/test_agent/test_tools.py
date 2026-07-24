"""Agent Tools 单元测试（mock 后端）。"""
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_fiber_connection_query():
    from src.tools.topology_tools import fiber_connection_query
    mock_data = {"fiber_id": 1001, "src_ne_id": 101, "dst_ne_id": 205}
    with patch("src.tools.topology_tools.backend.get_fiber",
               new_callable=AsyncMock, return_value=mock_data):
        result = await fiber_connection_query(fiber_id=1001)
        assert result["fiber_id"] == 1001

@pytest.mark.asyncio
async def test_colored_fibers_query():
    from src.tools.colored_tools import colored_fibers_query
    mock_data = {"fibers": [], "total": 0}
    with patch("src.tools.colored_tools.backend.get_colored",
               new_callable=AsyncMock, return_value=mock_data):
        result = await colored_fibers_query(color="RED")
        assert result["total"] == 0

@pytest.mark.asyncio
async def test_invalid_color():
    from src.tools.colored_tools import colored_fibers_query
    with pytest.raises(ValueError):
        await colored_fibers_query(color="BLUE")

@pytest.mark.asyncio
async def test_batch_over_limit():
    from src.tools.topology_tools import batch_fiber_connection_query
    with pytest.raises(ValueError):
        await batch_fiber_connection_query(fiber_ids=list(range(101)))