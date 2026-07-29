"""
Alarm tools: current alarm queries.

Maps to C++ API Gateway endpoints:
  - GET /api/v1/alarms/current?board_id=X&port_id=Y
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


class AlarmQueryInput(BaseModel):
    board_id: Optional[str] = Field(default=None, description="Board ID filter (optional)")
    port_id: Optional[str] = Field(default=None, description="Port ID filter (optional)")


@tool(args_schema=AlarmQueryInput)
async def alarm_query(board_id: Optional[str] = None, port_id: Optional[str] = None) -> str:
    """Query current active alarms, optionally filtered by board/port.
    Returns: JSON with alarms array (board_id, port_id, alarm_level, raised_at)."""
    params = {}
    if board_id:
        params["board_id"] = board_id
    if port_id:
        params["port_id"] = port_id
    return await fiber_http_client.get(
        "/api/v1/alarms/current",
        timeout=2.0,
        params=params if params else None,
    )
