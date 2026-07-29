"""
Topology tools: fiber connection queries and board queries.

Maps to C++ API Gateway endpoints:
  - GET  /api/v1/topology/fibers/{fiber_id}
  - POST /api/v1/topology/fibers/batch
  - GET  /api/v1/topology/fibers/{fiber_id}/scene
  - GET  /api/v1/boards/{board_id}
"""

from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client


# =============================================================================
# Pydantic Input Schemas
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
# Topology Tools
# =============================================================================

@tool(args_schema=FiberQueryInput)
async def fiber_connection_query(fiber_id: str) -> str:
    """Query single fiber connection info (inter-NE fiber link).
    Returns: fiber detail JSON (src_board, dst_board, src_ne, dst_ne)."""
    # Extract numeric ID from FIB-XXXX format
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/topology/fibers/{numeric_id}",
        timeout=2.0,
    )


@tool(args_schema=BatchFiberQueryInput)
async def batch_fiber_connection_query(fiber_ids: list[str], chunk_id: str) -> str:
    """Batch query fiber connections (chunked, max 50 per batch).
    Returns: batch result JSON with found/error_message markers."""
    numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]
    return await fiber_http_client.post(
        "/api/v1/topology/fibers/batch",
        json={"fiber_ids": [int(i) for i in numeric_ids], "chunk_id": chunk_id},
        timeout=5.0,
    )


@tool(args_schema=FiberSceneInput)
async def fiber_scene_query(fiber_id: str) -> str:
    """Query fiber scene info (full topology including NE-internal fibers, active/passive boards).
    Returns: scene detail JSON with src/dst boards, internal fibers, passive boards."""
    numeric_id = fiber_id.replace("FIB-", "")
    return await fiber_http_client.get(
        f"/api/v1/topology/fibers/{numeric_id}/scene",
        timeout=2.0,
    )


@tool(args_schema=BoardQueryInput)
async def board_query(board_id: str) -> str:
    """Query single board info (type, NE assignment, port status).
    Returns: board detail JSON (board_id, board_type, ne_id, ports)."""
    return await fiber_http_client.get(
        f"/api/v1/boards/{board_id}",
        timeout=2.0,
    )


@tool(args_schema=BatchBoardQueryInput)
async def batch_board_query(board_ids: list[str]) -> str:
    """Batch query board info.
    Returns: batch result JSON array with found/error markers."""
    return await fiber_http_client.post(
        "/api/v1/boards/batch",
        json={"board_ids": [int(i) for i in board_ids]},
        timeout=5.0,
    )
