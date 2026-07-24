"""记忆类 Tools（analysis-expert）：分析结果持久化 + 对比分析。"""
import json
from src.tools.registry import tool
from src.memory.store import memory

@tool(name="memory_save", tags=["memory"])
async def memory_save(fiber_id: int, analysis_type: str,
                      result_json: str, summary: str) -> dict:
    """持久化保存一次分析结果（用于后续对比分析）。

    Args:
        fiber_id: 光纤 ID
        analysis_type: 分析类型 spanloss|color|trend|health
        result_json: 分析结果 JSON 字符串
        summary: 结果摘要
    """
    rid = await memory.save_analysis(fiber_id, analysis_type,
                                     json.loads(result_json), summary)
    return {"saved": True, "id": rid}

@tool(name="memory_query", tags=["memory"])
async def memory_query(fiber_id: int | None = None,
                       analysis_type: str | None = None,
                       start_time: str | None = None,
                       end_time: str | None = None,
                       limit: int = 10) -> dict:
    """查询历史分析结果（支持按光纤/类型/时间范围过滤）。

    Args:
        fiber_id: 光纤 ID（可选）
        analysis_type: 分析类型（可选）
        start_time: 起始时间 ISO 8601（可选）
        end_time: 结束时间 ISO 8601（可选）
        limit: 最大返回条数
    """
    rows = await memory.query_analysis(fiber_id, analysis_type,
                                       start_time, end_time, limit)
    return {"count": len(rows), "records": rows}