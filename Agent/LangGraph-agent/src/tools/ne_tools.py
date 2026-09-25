"""
网元（Network Element）工具集 [v7.1]。

注意：后端 API Gateway 尚未注册 /api/v1/nes/* 路由。
当前返回友好提示，待后端实现后恢复真实 HTTP 调用。

计划中的接口（尚未可用）：
  - GET /api/v1/nes/{ne_id}
  - GET /api/v1/nes/{ne_id}/boards
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import assert_positive_int, make_error_json


class NeQueryInput(BaseModel):
    ne_id: int = Field(description="Network Element ID (positive integer)")
    include_boards: bool = Field(default=False, description="Include board list")


@tool(args_schema=NeQueryInput)
async def ne_query(ne_id: int, include_boards: bool = False) -> str:
    """查询网元信息（名称、类型、位置、状态）。
    可选择包含关联的单盘列表。
    返回：JSON，含 ne_id、ne_name、ne_type、status、boards（可选）。"""
    # Layer 3 断言
    assert_positive_int(ne_id, "ne_id")

    # TODO: 后端 API Gateway 尚未注册 /api/v1/nes/* 路由，暂时返回友好提示
    # 待后端实现后，取消以下注释并删除 return make_error_json(...) 行：
    # result = await fiber_http_client.get(f"/api/v1/nes/{ne_id}", timeout=2.0)
    # if include_boards:
    #     boards = await fiber_http_client.get(f"/api/v1/nes/{ne_id}/boards", timeout=2.0)
    #     import json
    #     ne_data = json.loads(result)
    #     ne_data["boards"] = json.loads(boards)
    #     return json.dumps(ne_data, ensure_ascii=False)
    # return result
    return make_error_json(
        "NE_SERVICE_UNAVAILABLE",
        f"网元查询服务暂不可用 (ne_id={ne_id})",
        "后端 API Gateway 尚未注册 /api/v1/nes/* 路由，待后续版本启用",
    )
