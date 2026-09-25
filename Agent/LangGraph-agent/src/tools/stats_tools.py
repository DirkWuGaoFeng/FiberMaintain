"""
统计工具集 —— 实时统计和趋势查询。

【对应后端 API】
  - GET /api/v1/fibers/stats/realtime                      — 实时统计（总数、颜色分布、告警数）
  - GET /api/v1/fibers/stats/trend?start_time=X&end_time=Y — 趋势数据
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


class StatsRealtimeInput(BaseModel):
    pass  # 无需参数


class StatsTrendInput(BaseModel):
    start_time: Optional[str] = Field(default=None, description="Start time (ISO format)")
    end_time: Optional[str] = Field(default=None, description="End time (ISO format)")


@tool(args_schema=StatsRealtimeInput)
async def fiber_stats_query() -> str:
    """查询光纤实时统计（总数、红/黄/绿数量、活动告警数）。
    返回：JSON，含 total_fibers, red_count, yellow_count, green_count, active_alarms。"""
    return await fiber_http_client.get(
        "/api/v1/fibers/stats/realtime",
        timeout=2.0,
    )


@tool(args_schema=StatsTrendInput)
async def fiber_trend_query(start_time: Optional[str] = None, end_time: Optional[str] = None) -> str:
    """查询光纤统计趋势数据（随时间变化）。
    返回：JSON，含数据点数组（timestamp, red_count, yellow_count, total_colored）。"""
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
