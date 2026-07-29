"""
Performance tools: fiber performance and span loss queries.

Maps to C++ API Gateway endpoints:
  - GET /api/v1/fibers/{fiber_id}/performance
  - GET /api/v1/fibers/{fiber_id}/spanloss
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
    """Query fiber performance metrics (src OOP, dst IOP, error code).
    Returns: JSON with fiber_id, src_oop, dst_iop, error_code, error_message."""
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/fibers/{numeric_id}/performance",
        timeout=2.0,
    )


@tool(args_schema=FiberSpanlossInput)
async def fiber_spanloss_query(fiber_id: str) -> str:
    """Query fiber span loss (total attenuation in dB).
    Returns: JSON with fiber_id and spanloss value."""
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/fibers/{numeric_id}/spanloss",
        timeout=2.0,
    )
