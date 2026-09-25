"""
批量工具集 —— 批量查询光纤性能、跨段衰耗、告警与连接关系。

这些工具通过 Send 机制由 batch_processor 子图调用。
每个工具都接收 chunk_id 用于幂等跟踪。

对应 C++ API Gateway 的批量接口：
  - POST /api/v1/topology/fibers/batch
  - POST /api/v1/boards/batch
  - POST /api/v1/fibers/performance/batch  （经由单条调用聚合）
  - POST /api/v1/fibers/spanloss/batch     （经由单条调用聚合）
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
# 输入参数契约（Input Schemas）
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
# 批量工具（Batch Tools）
# =============================================================================


@tool(args_schema=BatchPerformanceInput)
async def batch_fiber_performance_query(fiber_ids: list[str], chunk_id: str) -> str:
    """批量查询多条光纤的性能指标。
    逐条查询每条光纤并汇总结果。
    返回：JSON，包含结果数组与错误汇总。"""
    results = []
    errors = []
    numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]

    # 在块内并发查询各光纤
    tasks = [fiber_http_client.get(f"/api/v1/fibers/{fid}/performance", timeout=3.0) for fid in numeric_ids]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for fid, resp in zip(numeric_ids, responses):
        if isinstance(resp, Exception):
            errors.append({"fiber_id": fid, "error": str(resp)})
        else:
            try:
                results.append(json.loads(resp))
            except json.JSONDecodeError:
                errors.append({"fiber_id": fid, "error": "Invalid JSON response"})

    return json.dumps(
        {
            "chunk_id": chunk_id,
            "count": len(results),
            "results": results,
            "errors": errors,
        },
        ensure_ascii=False,
    )


@tool(args_schema=BatchSpanlossInput)
async def batch_fiber_spanloss_query(fiber_ids: list[str], chunk_id: str) -> str:
    """批量查询多条光纤的跨段衰耗。
    返回：JSON，包含结果数组（fiber_id，每条光纤的 spanloss）。"""
    results = []
    errors = []
    numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]

    tasks = [fiber_http_client.get(f"/api/v1/fibers/{fid}/spanloss", timeout=3.0) for fid in numeric_ids]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for fid, resp in zip(numeric_ids, responses):
        if isinstance(resp, Exception):
            errors.append({"fiber_id": fid, "error": str(resp)})
        else:
            try:
                results.append(json.loads(resp))
            except json.JSONDecodeError:
                errors.append({"fiber_id": fid, "error": "Invalid JSON response"})

    return json.dumps(
        {
            "chunk_id": chunk_id,
            "count": len(results),
            "results": results,
            "errors": errors,
        },
        ensure_ascii=False,
    )


@tool(args_schema=BatchAlarmInput)
async def batch_alarm_query(board_ids: list[str], chunk_id: str) -> str:
    """批量查询多个单盘的告警。
    返回：JSON，汇总所有单盘的告警。"""
    all_alarms = []
    errors = []

    tasks = [
        fiber_http_client.get("/api/v1/alarms/current", timeout=3.0, params={"board_id": bid}) for bid in board_ids
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

    return json.dumps(
        {
            "chunk_id": chunk_id,
            "total_alarms": len(all_alarms),
            "alarms": all_alarms,
            "errors": errors,
        },
        ensure_ascii=False,
    )


@tool(args_schema=BatchConnectionInput)
async def batch_fiber_connection_query(fiber_ids: list[str], chunk_id: str) -> str:
    """通过拓扑批量接口批量查询光纤连接关系。
    返回：JSON，为后端批量查询结果。"""
    numeric_ids = [int(fid.replace("FIB-", "")) for fid in fiber_ids]
    return await fiber_http_client.post(
        "/api/v1/topology/fibers/batch",
        json={"fiber_ids": numeric_ids, "chunk_id": chunk_id},
        timeout=5.0,
    )
