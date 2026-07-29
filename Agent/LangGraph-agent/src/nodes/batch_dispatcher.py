"""
Batch dispatcher node: splits fiber IDs into chunks and dispatches via Send.
"""

from __future__ import annotations

import logging
import os

from langgraph.types import Send

from ..graph.state import FiberAgentState

logger = logging.getLogger(__name__)

CHUNK_SIZE = int(os.environ.get("BATCH_CHUNK_SIZE", "50"))
MAX_TOTAL = int(os.environ.get("BATCH_MAX_TOTAL", "200"))


def batch_dispatcher_node(state: FiberAgentState) -> list[Send]:
    """
    Batch dispatch node: splits N fiber IDs into chunks of <=50,
    dispatches each chunk as a Send for parallel execution.
    LangGraph automatically runs all Send targets concurrently.
    """
    intent = state.get("intent")
    fiber_ids = intent.fiber_ids if intent else []

    if not fiber_ids:
        logger.warning("[BatchDispatcher] No fiber IDs in intent")
        return []

    if len(fiber_ids) > MAX_TOTAL:
        logger.warning(f"[BatchDispatcher] Exceeds max {MAX_TOTAL}, truncating")
        fiber_ids = fiber_ids[:MAX_TOTAL]

    # Split into chunks
    chunks = [
        fiber_ids[i:i + CHUNK_SIZE]
        for i in range(0, len(fiber_ids), CHUNK_SIZE)
    ]

    trace_id = state.get("trace_id", "unknown")
    sends = []
    for idx, chunk in enumerate(chunks):
        chunk_id = f"{trace_id}_chunk_{idx}"
        sends.append(
            Send(
                "batch_worker",
                {
                    "chunk_id": chunk_id,
                    "fiber_ids": chunk,
                    "chunk_index": idx,
                    "idempotency_key": chunk_id,
                    "result": None,
                    "error": None,
                },
            )
        )

    logger.info(f"[BatchDispatcher] Dispatching {len(sends)} chunks ({len(fiber_ids)} fibers)")
    return sends
