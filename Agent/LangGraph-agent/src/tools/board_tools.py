"""
Board tools: board-specific fiber queries [v7.1].

Extends topology_tools.board_query with fiber association queries.

Maps to C++ API Gateway endpoints:
  - GET /api/v1/boards/{board_id}/fibers
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import assert_positive_int, fiber_http_client, make_error_json


class BoardFibersInput(BaseModel):
    board_id: int = Field(description="Board ID (positive integer)")


@tool(args_schema=BoardFibersInput)
async def board_fibers_query(board_id: int) -> str:
    """Query all fibers connected to a specific board.
    Returns: JSON with fibers array (fiber_id, port_id, color, remote_ne)."""
    # Layer 3 assertion
    assert_positive_int(board_id, "board_id")

    try:
        return await fiber_http_client.get(
            f"/api/v1/boards/{board_id}/fibers",
            timeout=2.0,
        )
    except Exception as e:
        return make_error_json("BOARD_FIBERS_FAILED", str(e), "确认板卡ID是否存在")
