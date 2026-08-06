"""
Network Element (NE) tools [v7.1].

Maps to C++ API Gateway endpoints:
  - GET /api/v1/nes/{ne_id}
  - GET /api/v1/nes/{ne_id}/boards
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import assert_positive_int, fiber_http_client, make_error_json


class NeQueryInput(BaseModel):
    ne_id: int = Field(description="Network Element ID (positive integer)")
    include_boards: bool = Field(default=False, description="Include board list")


@tool(args_schema=NeQueryInput)
async def ne_query(ne_id: int, include_boards: bool = False) -> str:
    """Query network element info (name, type, location, status).
    Optionally include associated boards.
    Returns: JSON with ne_id, ne_name, ne_type, status, boards(optional)."""
    # Layer 3 assertion
    assert_positive_int(ne_id, "ne_id")

    try:
        result = await fiber_http_client.get(
            f"/api/v1/nes/{ne_id}",
            timeout=2.0,
        )
        if include_boards:
            boards = await fiber_http_client.get(
                f"/api/v1/nes/{ne_id}/boards",
                timeout=2.0,
            )
            import json
            ne_data = json.loads(result)
            ne_data["boards"] = json.loads(boards)
            return json.dumps(ne_data, ensure_ascii=False)
        return result
    except Exception as e:
        return make_error_json("NE_QUERY_FAILED", str(e), "确认网元ID是否存在")
