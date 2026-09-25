"""
颜色光纤工具集 —— 按颜色状态查询光纤。

【对应后端 API】
  - GET /api/v1/fibers/colored?color=X    — 按颜色查询（RED/YELLOW/GREEN）
  - GET /api/v1/fibers/colored/all        — 查询所有颜色光纤

【颜色含义】
  - RED：严重异常（中断/严重超标）
  - YELLOW：告警状态（性能偏高）
  - GREEN：正常状态
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


class ColoredFiberInput(BaseModel):
    color: str = Field(description="Color filter: RED, YELLOW, or GREEN")


class AllColoredFiberInput(BaseModel):
    pass  # 无需参数


@tool(args_schema=ColoredFiberInput)
async def colored_fibers_query(color: str) -> str:
    """按颜色状态查询光纤（RED/YELLOW/GREEN）。
    返回：JSON，含光纤数组（fiber info, color, scenario_type）。"""
    return await fiber_http_client.get(
        "/api/v1/fibers/colored",
        timeout=2.0,
        params={"color": color.upper()},
    )


@tool(args_schema=AllColoredFiberInput)
async def all_colored_fibers_query() -> str:
    """查询所有颜色光纤（RED + YELLOW + GREEN）。
    返回：JSON，含所有颜色光纤数组。"""
    return await fiber_http_client.get(
        "/api/v1/fibers/colored/all",
        timeout=3.0,
    )
