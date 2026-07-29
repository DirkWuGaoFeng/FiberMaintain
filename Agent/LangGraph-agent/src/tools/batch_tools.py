"""
Batch tools: batch fiber performance, spanloss, alarm, and connection queries.

These tools are used by the batch_processor sub-graph via Send mechanism.
Each tool accepts a chunk_id for idempotency tracking.

Maps to C++ API Gateway batch endpoints:
  - POST /api/v1/topology/fibers/batch
  - POST /api/v1/boards/batch
  - POST /api/v1/fibers/performance/batch  (via individual calls)
  - POST /api/v1/fibers/spanloss/batch     (via individual calls)
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import fiber_http_client

logger = logging.getLogger(__name__)


# =============================================================================
# Input Schemas
# =============================================================================

class BatchPerformanceInput(BaseModel):
    fiber_ids: list[str] = Field(description="Fiber IDs to query (max 50)")
    chunk_id: str = Field(description="Chunk unique ID for idempotency")


class BatchSpanlossInput(BaseModel):
    fiber_ids: list[str] = Field(description="Fiber IDs to query (max 50)")
    chunk_id: str = Field(description="Chunk unique ID for idempotency")


class BatchAlarmInput(BaseModel):
    board_ids: list[str] = Field(description="Board IDs to query alarms")
    chunk_id: str = Field(description="Chunk unique ID for idempotency")


class BatchConnectionInput(BaseModel):
    fiber_ids: list[str] = Field(description="Fiber IDs to query (max 50)")
    chunk_id: str = Field(description="Chunk unique ID for idempotency")


# =============================================================================
# Batch Tools
# =============================================================================

@tool(args_schema=BatchPerformanceInput)
async def batch_fiber_performance_query(fiber_ids: list[str], chunk_id: str) -> str:
    """Batch query fiber performance metrics for multiple fibers.
    Queries each fiber individually and aggregates results.
    Returns: JSON with results array and error summary."""
    results = []
    errors = []
    numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]

    # Query each fiber concurrently within the chunk
    tasks = [
        fiber_http_client.get(f"/api/v1/fibers/{fid}/performance", timeout=3.0)
        for fid in numeric_ids
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for fid, resp in zip(numeric_ids, responses):
        if isinstance(resp, Exception):
            errors.append({"fiber_id": fid, "error": str(resp)})
        else:
            try:
                results.append(json.loads(resp))
            except json.JSONDecodeError:
                errors.append({"fiber_id": fid, "error": "Invalid JSON response"})

    return json.dumps({
        "chunk_id": chunk_id,
        "count": len(results),
        "results": results,
        "errors": errors,
    }, ensure_ascii=False)


@tool(args_schema=BatchSpanlossInput)
async def batch_fiber_spanloss_query(fiber_ids: list[str], chunk_id: str) -> str:
    """Batch query fiber span loss for multiple fibers.
    Returns: JSON with results array (fiber_id, spanloss per fiber)."""
    results = []
    errors = []
    numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]

    tasks = [
        fiber_http_client.get(f"/api/v1/fibers/{fid}/spanloss", timeout=3.0)
        for fid in numeric_ids
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for fid, resp in zip(numeric_ids, responses):
        if isinstance(resp, Exception):
            errors.append({"fiber_id": fid, "error": str(resp)})
        else:
            try:
                results.append(json.loads(resp))
            except json.JSONDecodeError:
                errors.append({"fiber_id": fid, "error": "Invalid JSON response"})

    return json.dumps({
        "chunk_id": chunk_id,
        "count": len(results),
        "results": results,
        "errors": errors,
    }, ensure_ascii=False)


@tool(args_schema=BatchAlarmInput)
async def batch_alarm_query(board_ids: list[str], chunk_id: str) -> str:
    """Batch query alarms for multiple boards.
    Returns: JSON with alarms aggregated across all boards."""
    all_alarms = []
    errors = []

    tasks = [
        fiber_http_client.get("/api/v1/alarms/current", timeout=3.0, params={"board_id": bid})
        for bid in board_ids
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for bid, resp in zip(board_ids, responses):
        if isinstance(resp, Exception):
            errors.append({"board_id": bid, "error": str(resp)})
        else:
            try:
                data = json.loads(resp)
                if "alarms" in data:
                    all_alarms.extend(data["alarms"])
            except json.JSONDecodeError:
                errors.append({"board_id": bid, "error": "Invalid JSON response"})

    return json.dumps({
        "chunk_id": chunk_id,
        "total_alarms": len(all_alarms),
        "alarms": all_alarms,
        "errors": errors,
    }, ensure_ascii=False)


@tool(args_schema=BatchConnectionInput)
async def batch_fiber_connection_query(fiber_ids: list[str], chunk_id: str) -> str:
    """Batch query fiber connections via the topology batch endpoint.
    Returns: JSON with batch result from backend."""
    numeric_ids = [int(fid.replace("FIB-", "")) for fid in fiber_ids]
    return await fiber_http_client.post(
        "/api/v1/topology/fibers/batch",
        json={"fiber_ids": numeric_ids, "chunk_id": chunk_id},
        timeout=5.0,
    )
