"""
Colored fiber tools: query fibers by color status.

Maps to C++ API Gateway endpoints:
  - GET /api/v1/fibers/colored?color=X
  - GET /api/v1/fibers/colored/all
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


class ColoredFiberInput(BaseModel):
    color: str = Field(description="Color filter: RED, YELLOW, or GREEN")


class AllColoredFiberInput(BaseModel):
    pass  # No parameters needed


@tool(args_schema=ColoredFiberInput)
async def colored_fibers_query(color: str) -> str:
    """Query fibers with specific color status (RED/YELLOW/GREEN).
    Returns: JSON with fibers array (fiber info, color, scenario_type)."""
    return await fiber_http_client.get(
        "/api/v1/fibers/colored",
        timeout=2.0,
        params={"color": color.upper()},
    )


@tool(args_schema=AllColoredFiberInput)
async def all_colored_fibers_query() -> str:
    """Query all colored fibers (RED + YELLOW + GREEN).
    Returns: JSON with all colored fibers array."""
    return await fiber_http_client.get(
        "/api/v1/fibers/colored/all",
        timeout=3.0,
    )
