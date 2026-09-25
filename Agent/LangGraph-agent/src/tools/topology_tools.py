"""
拓扑工具集 —— 光纤连接查询和单盘查询。

【对应后端 API】
  - GET  /api/v1/topology/fibers/{fiber_id}      — 单条光纤连接信息
  - POST /api/v1/topology/fibers/batch             — 批量光纤连接查询
  - GET  /api/v1/topology/fibers/{fiber_id}/scene  — 光纤场景图（含网元内部光纤）
  - GET  /api/v1/boards/{board_id}                 — 单盘信息
  - POST /api/v1/boards/batch                      — 批量单盘查询

【面试知识点】
  - @tool 装饰器将函数注册为 LangChain Tool，LLM 可通过 function calling 调用
  - args_schema 使用 Pydantic 模型，强制 LLM 传入结构化参数
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client

# =============================================================================
# Pydantic 输入模式
# 【设计说明】定义 LLM 调用工具时的参数约束和描述
# =============================================================================


class FiberQueryInput(BaseModel):
    fiber_id: str = Field(description="Fiber ID, format: FIB-XXXX (4-digit number)")


class BoardQueryInput(BaseModel):
    board_id: str = Field(description="Board ID (numeric)")


class FiberSceneInput(BaseModel):
    fiber_id: str = Field(description="Fiber ID for scene query")


class BatchFiberQueryInput(BaseModel):
    fiber_ids: list[str] = Field(description="List of fiber IDs (max 50 per chunk)")
    chunk_id: str = Field(description="Unique chunk identifier (idempotency key)")


class BatchBoardQueryInput(BaseModel):
    board_ids: list[str] = Field(description="List of board IDs")


# =============================================================================
# 拓扑工具
# 【设计说明】每个工具对应一个后端 API，使用 @tool 装饰器注册
# =============================================================================


@tool(args_schema=FiberQueryInput)
async def fiber_connection_query(fiber_id: str) -> str:
    """查询单条光纤连接信息（网元间光纤链路）。
    返回：光纤详情 JSON（src_board, dst_board, src_ne, dst_ne）。"""
    # 从 FIB-XXXX 格式提取数字 ID
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/topology/fibers/{numeric_id}",
        timeout=2.0,
    )


@tool(args_schema=BatchFiberQueryInput)
async def batch_fiber_connection_query(fiber_ids: list[str], chunk_id: str) -> str:
    """批量查询光纤连接（分块，每块最多 50 条）。
    返回：批量结果 JSON，含 found/error_message 标记。"""
    numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]
    return await fiber_http_client.post(
        "/api/v1/topology/fibers/batch",
        json={"fiber_ids": [int(i) for i in numeric_ids], "chunk_id": chunk_id},
        timeout=5.0,
    )


@tool(args_schema=FiberSceneInput)
async def fiber_scene_query(fiber_id: str) -> str:
    """查询光纤场景信息（完整拓扑，含网元内部光纤、主备盘）。
    返回：场景详情 JSON（src/dst 板卡、内部光纤、备用盘）。"""
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/topology/fibers/{numeric_id}/scene",
        timeout=2.0,
    )


@tool(args_schema=BoardQueryInput)
async def board_query(board_id: str) -> str:
    """查询单盘信息（类型、网元分配、端口状态）。
    返回：单盘详情 JSON（board_id, board_type, ne_id, ports）。"""
    return await fiber_http_client.get(
        f"/api/v1/boards/{board_id}",
        timeout=2.0,
    )


@tool(args_schema=BatchBoardQueryInput)
async def batch_board_query(board_ids: list[str]) -> str:
    """批量查询单盘信息。
    返回：批量结果 JSON 数组，含 found/error 标记。"""
    return await fiber_http_client.post(
        "/api/v1/boards/batch",
        json={"board_ids": [int(i) for i in board_ids]},
        timeout=5.0,
    )
