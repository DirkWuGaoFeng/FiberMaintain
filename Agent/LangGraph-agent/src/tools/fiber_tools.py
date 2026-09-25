"""
光纤工具集 —— 历史性能查询 [v7.1]。

【功能说明】
扩展 performance_tools，支持时间范围的历史性能查询。

【对应后端 API】
  - GET /api/v1/fibers/{fiber_id}/performance/history?start_time=X&end_time=Y
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import assert_positive_int, fiber_http_client, make_error_json


class FiberHistoryPerformanceInput(BaseModel):
    fiber_id: int = Field(description="Fiber ID (positive integer)")
    start_time: Optional[str] = Field(default=None, description="Start time ISO 8601")
    end_time: Optional[str] = Field(default=None, description="End time ISO 8601")


@tool(args_schema=FiberHistoryPerformanceInput)
async def fiber_history_performance(
    fiber_id: int,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """查询光纤历史性能数据（指定时间范围）。
    返回：JSON，含性能点数组（timestamp, oop, iop, spanloss）。"""
    # Layer 3 断言：确保 fiber_id 是正整数
    assert_positive_int(fiber_id, "fiber_id")

    params = {}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time

    try:
        return await fiber_http_client.get(
            f"/api/v1/fibers/{fiber_id}/performance/history",
            timeout=3.0,
            params=params if params else None,
        )
    except Exception as e:
        return make_error_json("HISTORY_QUERY_FAILED", str(e), "检查时间范围格式和光纤ID")
