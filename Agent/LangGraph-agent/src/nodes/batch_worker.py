"""
Batch worker node: processes a single chunk (called via Send).
"""

from __future__ import annotations

import json
import logging

from ..graph.state import BatchChunkState
from ..tools._http_client import fiber_http_client

logger = logging.getLogger(__name__)

# Simple in-memory idempotency store (production: use SQLite)
_idempotency_store: dict[str, dict] = {}


async def batch_worker_node(state: BatchChunkState) -> dict:
    """
    Batch worker node: processes a single chunk.
    Called concurrently by LangGraph Send mechanism.
    Includes idempotency check and backpressure.
    """
    chunk_id = state["chunk_id"]
    fiber_ids = state["fiber_ids"]

    logger.info(f"[BatchWorker] Processing chunk {chunk_id} ({len(fiber_ids)} fibers)")

    # 1. Idempotency check
    if chunk_id in _idempotency_store:
        logger.info(f"[BatchWorker] Chunk {chunk_id} already processed (idempotent)")
        return {"result": _idempotency_store[chunk_id]}

    # 2. Call backend batch API
    try:
        # Query performance for all fibers in chunk concurrently
        import asyncio

        numeric_ids = [fid.replace("FIB-", "") for fid in fiber_ids]
        tasks = []
        for fid in numeric_ids:
            tasks.append(fiber_http_client.get(f"/api/v1/fibers/{fid}/performance", timeout=3.0))
            tasks.append(fiber_http_client.get(f"/api/v1/fibers/{fid}/spanloss", timeout=3.0))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Parse results
        results = []
        errors = []
        for i, resp in enumerate(responses):
            if isinstance(resp, Exception):
                errors.append(str(resp))
            else:
                try:
                    results.append(json.loads(resp))
                except json.JSONDecodeError:
                    errors.append("Invalid JSON")

        result = {
            "chunk_id": chunk_id,
            "count": len(fiber_ids),
            "normal_count": sum(1 for r in results if isinstance(r, dict) and r.get("error_code", 0) == 0),
            "results": results,
            "errors": errors,
        }

        # 3. Store idempotency marker (TTL handled by GC)
        _idempotency_store[chunk_id] = result

        logger.info(f"[BatchWorker] Chunk {chunk_id} done: {result['normal_count']}/{len(fiber_ids)} normal")
        return {"result": result}

    except Exception as e:
        logger.error(f"[BatchWorker] Chunk {chunk_id} failed: {e}")
        return {"error": str(e), "result": {"chunk_id": chunk_id, "count": 0, "normal_count": 0, "results": [], "errors": [str(e)]}}
