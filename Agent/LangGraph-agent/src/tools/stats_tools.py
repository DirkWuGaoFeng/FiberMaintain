"""
Stats tools: realtime statistics and trend queries.

Maps to C++ API Gateway endpoints:
  - GET /api/v1/fibers/stats/realtime
  - GET /api/v1/fibers/stats/trend?start_time=X&end_time=Y
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


class StatsRealtimeInput(BaseModel):
    pass  # No parameters needed


class StatsTrendInput(BaseModel):
    start_time: Optional[str] = Field(default=None, description="Start time (ISO format)")
    end_time: Optional[str] = Field(default=None, description="End time (ISO format)")


@tool(args_schema=StatsRealtimeInput)
async def fiber_stats_query() -> str:
    """Query realtime fiber statistics (total, red/yellow/green counts, active alarms).
    Returns: JSON with total_fibers, red_count, yellow_count, green_count, active_alarms."""
    return await fiber_http_client.get(
        "/api/v1/fibers/stats/realtime",
        timeout=2.0,
    )


@tool(args_schema=StatsTrendInput)
async def fiber_trend_query(start_time: Optional[str] = None, end_time: Optional[str] = None) -> str:
    """Query fiber statistics trend over time.
    Returns: JSON with points array (timestamp, red_count, yellow_count, total_colored)."""
    params = {}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    return await fiber_http_client.get(
        "/api/v1/fibers/stats/trend",
        timeout=3.0,
        params=params if params else None,
    )
