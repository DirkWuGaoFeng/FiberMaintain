"""
告警工具集 —— 当前活动告警查询。

【对应后端 API】
  - GET /api/v1/alarms/current?board_id=X&port_id=Y — 查询当前告警

【告警级别】
  - CRITICAL：严重告警，需立即处理
  - MAJOR：主要告警，需尽快处理
  - MINOR：次要告警，可计划处理
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
    """查询当前活动告警，可按单盘/端口过滤。
    返回：JSON，含告警数组（board_id, port_id, alarm_level, raised_at）。"""
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
