"""统计/趋势类 Tools（data-collector / analysis-expert）。"""
from src.tools.registry import tool
from src.mcp import backend

@tool(name="fiber_stats_query", tags=["stats"])
async def fiber_stats_query() -> dict:
    """查询实时统计：当前红色/黄色连纤数量、活跃告警数。"""
    return await backend.get_stats_realtime()

@tool(name="fiber_trend_query", tags=["stats"])
async def fiber_trend_query(start_time: str, end_time: str) -> dict:
    """查询颜色数量时间序列趋势（5 分钟粒度，数据保留 7 天）。

    Args:
        start_time: 起始时间，ISO 8601，如 2026-07-21T00:00:00+08:00
        end_time: 结束时间，ISO 8601
    """
    return await backend.get_stats_trend(start_time, end_time)