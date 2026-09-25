"""
批量派发器节点 —— 将批量查询拆分为分块并行执行。

【功能说明】
使用 LangGraph Send 实现 map-reduce 模式。
分块大小：每块 50 条光纤，最多 200 条。

【处理流程】
1. 颜色查询 → 调用 /fibers/colored API
2. 指定光纤ID → 拆分为块，调用 /topology/fibers/batch
3. 无参数 → 调用统计概览 API

【面试知识点】
  Q: 为什么需要分块？
  A: 后端 API 有单次请求上限（BATCH_CHUNK_SIZE=50），
     分块可以控制单次请求的数据量，避免超时和内存溢出。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..config import BATCH_CHUNK_SIZE, BATCH_MAX_TOTAL
from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)


async def batch_dispatcher_node(state: MainGraphState) -> dict:
    """批量派发器：拆分光纤ID为块并执行查询。

    【功能说明】
    MVP 阶段：顺序执行并聚合结果。
    生产环境：使用 LangGraph Send 并行派发。

    【输入】state.normalized_params（含 fiber_ids, color）
    【输出】final_output（聚合结果摘要）
    【状态更新】batch_results, batch_progress, collected_data_summary
    """
    params = state.get("normalized_params", {})
    fiber_ids = params.get("fiber_ids", [])
    color = params.get("color")

    # 如果是颜色查询，使用颜色查询 API
    if color and not fiber_ids:
        return await _handle_color_batch(color)

    # 限制总量
    if len(fiber_ids) > BATCH_MAX_TOTAL:
        fiber_ids = fiber_ids[:BATCH_MAX_TOTAL]

    if not fiber_ids:
        # 默认：查询统计概览
        return await _handle_stats_batch()

    # 拆分为块
    chunks = [fiber_ids[i : i + BATCH_CHUNK_SIZE] for i in range(0, len(fiber_ids), BATCH_CHUNK_SIZE)]

    logger.info(f"[BatchDispatcher] Processing {len(fiber_ids)} fibers in {len(chunks)} chunks")

    # 执行各块（MVP 阶段为顺序执行）
    import json

    from ..tools._http_client import fiber_http_client

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

    # 聚合结果
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
    """处理基于颜色的批量查询（如“查询所有红色光纤”）。"""
    import json

    from ..tools._http_client import fiber_http_client

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
    """处理统计概览查询（如“光纤总数”“颜色分布”）。"""
    from ..tools._http_client import fiber_http_client

    try:
        resp = await fiber_http_client.get("/api/v1/fibers/stats/realtime")
        return {
            "messages": [AIMessage(content=f"📊 光纤统计：{resp[:500]}")],
            "final_output": f"📊 光纤统计：{resp[:500]}",
            "collected_data_summary": resp[:500],
        }
    except Exception as e:
        msg = f"查询失败：{e}"
        return {"messages": [AIMessage(content=msg)], "final_output": msg}


def _aggregate_results(results: list, total: int) -> str:
    """聚合批量查询结果，生成摘要文本。"""
    errors = sum(1 for r in results if isinstance(r, dict) and r.get("error"))
    success = len(results) - errors

    lines = [f"📊 批量查询完成：共 {total} 条光纤，成功获取 {success} 条结果"]
    if errors:
        lines.append(f"  ⚠️ {errors} 条查询失败")

    return "\n".join(lines)
