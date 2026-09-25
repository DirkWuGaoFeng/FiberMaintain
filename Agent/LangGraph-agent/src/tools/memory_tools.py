"""
记忆工具集 —— 通过 SQLite 实现长期记忆的保存与查询。

这些工具由 analysis_expert 和 knowledge_assistant 子图使用。
仅在颜色变化时才写入（以最小化存储占用）。
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 延迟初始化的记忆存储
_memory_store = None


def init_memory_tools(store) -> None:
    """使用共享的 MemoryStore 实例初始化记忆工具。"""
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
    """将光纤指标快照保存到长期记忆（仅在颜色变化时写入）。
    返回：确认消息。"""
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
    """查询光纤历史指标快照。
    返回：历史记录的 JSON 数组。"""
    if _memory_store is None:
        return json.dumps({"error": "Memory store not initialized", "records": []})

    try:
        records = await _memory_store.query(fiber_id, days=days)
        return json.dumps(records, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[Memory] Query failed: {e}")
        return json.dumps({"error": str(e), "records": []})
