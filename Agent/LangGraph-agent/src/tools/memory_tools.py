"""
Memory tools: long-term memory save and query via SQLite.

These tools are used by analysis_expert and knowledge_assistant sub-graphs.
Only writes when color changes (to minimize storage).
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Lazy-initialized memory store
_memory_store = None


def init_memory_tools(store) -> None:
    """Initialize memory tools with the shared MemoryStore instance."""
    global _memory_store
    _memory_store = store


class MemorySaveInput(BaseModel):
    fiber_id: str = Field(description="Fiber ID")
    spanloss: float = Field(description="Span loss value in dB")
    color: str = Field(description="Fiber color: GREEN, YELLOW, or RED")
    summary: str = Field(description="Brief analysis summary")


class MemoryQueryInput(BaseModel):
    fiber_id: str = Field(description="Fiber ID to query history")
    days: int = Field(default=30, description="Lookback period in days")


@tool(args_schema=MemorySaveInput)
async def memory_save(fiber_id: str, spanloss: float, color: str, summary: str) -> str:
    """Save fiber metric snapshot to long-term memory (only writes when color changes).
    Returns: confirmation message."""
    if _memory_store is None:
        return "Memory store not initialized"

    try:
        existing = await _memory_store.get_latest(fiber_id)
        if existing and existing.get("color") == color:
            return f"Color unchanged for {fiber_id}, skipping write"

        await _memory_store.save(fiber_id, spanloss, color, summary)
        return f"Saved {fiber_id} snapshot: {color}, {spanloss}dB"
    except Exception as e:
        logger.error(f"[Memory] Save failed: {e}")
        return f"Memory save failed: {e}"


@tool(args_schema=MemoryQueryInput)
async def memory_query(fiber_id: str, days: int = 30) -> str:
    """Query fiber historical metric snapshots.
    Returns: JSON array of historical records."""
    if _memory_store is None:
        return json.dumps({"error": "Memory store not initialized", "records": []})

    try:
        records = await _memory_store.query(fiber_id, days=days)
        return json.dumps(records, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[Memory] Query failed: {e}")
        return json.dumps({"error": str(e), "records": []})
