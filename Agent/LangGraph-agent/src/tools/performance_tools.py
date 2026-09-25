"""
性能工具集 —— 光纤性能指标和跨段衰耗查询。

【对应后端 API】
  - GET /api/v1/fibers/{fiber_id}/performance  — 实时性能（OOP/IOP）
  - GET /api/v1/fibers/{fiber_id}/spanloss     — 跨段衰耗（dB）

【指标说明】
  - OOP（Output Optical Power）：输出光功率，正常范围 -8.0 ~ -2.0 dBm
  - IOP（Input Optical Power）：输入光功率，正常范围 -15.0 ~ -8.0 dBm
  - Spanloss：跨段衰耗，告警阈值 5.0dB，严重阈值 8.0dB
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


class FiberPerformanceInput(BaseModel):
    fiber_id: str = Field(description="Fiber ID, format: FIB-XXXX")


class FiberSpanlossInput(BaseModel):
    fiber_id: str = Field(description="Fiber ID, format: FIB-XXXX")


@tool(args_schema=FiberPerformanceInput)
async def fiber_performance_query(fiber_id: str) -> str:
    """查询光纤性能指标（源端 OOP、目的端 IOP、错误码）。
    返回：JSON，含 fiber_id, src_oop, dst_iop, error_code, error_message。"""
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/fibers/{numeric_id}/performance",
        timeout=2.0,
    )


@tool(args_schema=FiberSpanlossInput)
async def fiber_spanloss_query(fiber_id: str) -> str:
    """查询光纤跨段衰耗（总衰耗，单位 dB）。
    返回：JSON，含 fiber_id 和 spanloss 值。"""
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/fibers/{numeric_id}/spanloss",
        timeout=2.0,
    )
