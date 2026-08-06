"""
Batch Dispatcher Node — Splits batch queries into chunks for parallel execution.

Uses LangGraph Send for map-reduce pattern.
Chunk size: 50 fibers per chunk, max 200 total.
"""

from __future__ import annotations

import logging
import uuid

from langchain_core.messages import AIMessage

from ..config import BATCH_CHUNK_SIZE, BATCH_MAX_TOTAL
from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def batch_dispatcher_node(state: MainGraphState) -> dict:
    """
    Batch dispatcher: split fiber IDs into chunks and execute queries.

    For MVP: executes sequentially and aggregates results.
    Production: would use LangGraph Send for parallel dispatch.
    """
    params = state.get("normalized_params", {})
    fiber_ids = params.get("fiber_ids", [])
    color = params.get("color")

    # If color query, use colored API
    if color and not fiber_ids:
        return await _handle_color_batch(color)

    # Limit total
    if len(fiber_ids) > BATCH_MAX_TOTAL:
        fiber_ids = fiber_ids[:BATCH_MAX_TOTAL]

    if not fiber_ids:
        # Default: query stats
        return await _handle_stats_batch()

    # Split into chunks
    chunks = [
        fiber_ids[i:i + BATCH_CHUNK_SIZE]
        for i in range(0, len(fiber_ids), BATCH_CHUNK_SIZE)
    ]

    logger.info(f"[BatchDispatcher] Processing {len(fiber_ids)} fibers in {len(chunks)} chunks")

    # Execute chunks (sequential for MVP)
    from ..tools._http_client import fiber_http_client
    import json

    results = []
    for chunk_idx, chunk in enumerate(chunks):
        try:
            resp = await fiber_http_client.post(
                "/api/v1/topology/fibers/batch",
                json={"fiber_ids": chunk},
                timeout=5.0,
            )
            data = json.loads(resp)
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict) and "fibers" in data:
                results.extend(data["fibers"])
            else:
                results.append(data)
        except Exception as e:
            logger.error(f"[BatchDispatcher] Chunk {chunk_idx} failed: {e}")
            results.append({"error": str(e), "chunk": chunk_idx})

    # Aggregate
    summary = _aggregate_results(results, len(fiber_ids))

    return {
        "messages": [AIMessage(content=summary)],
        "final_output": summary,
        "batch_results": results,
        "batch_progress": {"completed": len(fiber_ids), "total": len(fiber_ids), "percentage": 100},
        "collected_data_summary": summary,
        "processing_path": "heavy",
    }


async def _handle_color_batch(color: str) -> dict:
    """Handle color-based batch query."""
    from ..tools._http_client import fiber_http_client
    import json

    try:
        resp = await fiber_http_client.get("/api/v1/fibers/colored", params={"color": color})
        data = json.loads(resp)
        color_cn = {"RED": "红色", "YELLOW": "黄色", "GREEN": "绿色"}.get(color, color)

        if isinstance(data, dict) and "fibers" in data:
            count = len(data["fibers"])
            summary = f"📊 {color_cn}光纤共 {count} 条"
        elif isinstance(data, list):
            summary = f"📊 {color_cn}光纤共 {len(data)} 条"
        else:
            summary = f"📊 {color_cn}光纤查询结果：{str(data)[:300]}"

        return {
            "messages": [AIMessage(content=summary)],
            "final_output": summary,
            "collected_data_summary": summary,
        }
    except Exception as e:
        msg = f"查询失败：{e}"
        return {"messages": [AIMessage(content=msg)], "final_output": msg}


async def _handle_stats_batch() -> dict:
    """Handle stats overview query."""
    from ..tools._http_client import fiber_http_client

    try:
        resp = await fiber_http_client.get("/api/v1/fibers/stats")
        return {
            "messages": [AIMessage(content=f"📊 光纤统计：{resp[:500]}")],
            "final_output": f"📊 光纤统计：{resp[:500]}",
            "collected_data_summary": resp[:500],
        }
    except Exception as e:
        msg = f"查询失败：{e}"
        return {"messages": [AIMessage(content=msg)], "final_output": msg}


def _aggregate_results(results: list, total: int) -> str:
    """Aggregate batch results into summary."""
    errors = sum(1 for r in results if isinstance(r, dict) and r.get("error"))
    success = len(results) - errors

    lines = [f"📊 批量查询完成：共 {total} 条光纤，成功获取 {success} 条结果"]
    if errors:
        lines.append(f"  ⚠️ {errors} 条查询失败")

    return "\n".join(lines)
