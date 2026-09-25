"""
单盘工具集 —— 单盘关联光纤查询 [v7.1]。

【功能说明】
扩展 topology_tools.board_query，支持查询单盘关联的所有光纤。

【对应后端 API】
  - GET /api/v1/boards/{board_id}/fibers — 查询单盘关联光纤
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import assert_positive_int, fiber_http_client, make_error_json


class BoardFibersInput(BaseModel):
    board_id: int = Field(description="Board ID (positive integer)")


@tool(args_schema=BoardFibersInput)
async def board_fibers_query(board_id: int) -> str:
    """查询指定单盘关联的所有光纤。
    返回：JSON，含光纤数组（fiber_id, port_id, color, remote_ne）。"""
    # Layer 3 断言：确保 board_id 是正整数
    assert_positive_int(board_id, "board_id")

    try:
        return await fiber_http_client.get(
            f"/api/v1/boards/{board_id}/fibers",
            timeout=2.0,
        )
    except Exception as e:
        return make_error_json("BOARD_FIBERS_FAILED", str(e), "确认板卡ID是否存在")
