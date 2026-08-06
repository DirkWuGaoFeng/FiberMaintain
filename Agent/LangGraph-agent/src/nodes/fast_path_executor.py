"""
Fast Path Executor Node — Zero-LLM direct execution for rule-matched queries.

When rule engine hits with fast_path=True:
1. Directly call the corresponding backend API
2. Apply threshold-based judgment (programmatic)
3. Render output via template
4. Target latency: < 1s, zero LLM calls, zero tokens
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage

from ..config import SPANLOSS_CRITICAL, SPANLOSS_THRESHOLD
from ..graph.state import MainGraphState
from ..tools._http_client import fiber_http_client

logger = logging.getLogger(__name__)


# =============================================================================
# Output Templates
# =============================================================================

TEMPLATES = {
    "T_SPANLOSS": "光纤 {fiber_id} 当前衰耗为 {spanloss} dB（阈值 {threshold} dB），{status}。",
    "T_CONNECTION": "光纤 {fiber_id} 连纤信息：{data}",
    "T_PERFORMANCE": "光纤 {fiber_id} 性能数据：{data}",
    "T_FIBER_ALARM": "光纤 {fiber_id} 告警信息：{data}",
    "T_FIBER_STATUS": "光纤 {fiber_id} 状态：{data}",
    "T_PORT_ALARM": "{board_id}号盘{port_id}口 告警信息：{data}",
    "T_BOARD": "单盘 {board_id} 信息：{data}",
    "T_COLORED": "{color}光纤查询结果：{data}",
    "T_STATS": "光纤统计：{data}",
    "T_TREND": "光纤趋势数据：{data}",
}


async def fast_path_executor_node(state: MainGraphState) -> dict:
    """
    Fast Path executor: direct API call + template rendering.

    Handles rule-matched single queries without LLM involvement.
    """
    import time

    rule_match = state.get("rule_match", {})
    params = rule_match.get("params", {})
    template_id = rule_match.get("template_id", "T_FIBER_STATUS")
    intent = rule_match.get("intent", "single_query")
    trace_id = state.get("trace_id", "")
    start_time = time.time()

    logger.info(
        f"[TRACE:{trace_id}] [fast_path_executor] START "
        f"intent={intent} params={params} template={template_id}"
    )

    try:
        # Route to appropriate API based on intent
        if intent == "spanloss_query":
            result = await _query_spanloss(params)
        elif intent == "connection_query":
            result = await _query_connection(params)
        elif intent == "performance_query":
            result = await _query_performance(params)
        elif intent == "fiber_alarm_query":
            result = await _query_fiber_alarm(params)
        elif intent == "port_alarm_query":
            result = await _query_port_alarm(params)
        elif intent == "colored_query":
            result = await _query_colored(params)
        elif intent == "stats_query":
            result = await _query_stats(params)
        elif intent == "trend_query":
            result = await _query_trend(params)
        else:
            result = await _query_fiber_status(params)

        output = _render_template(template_id, params, result)
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        logger.info(
            f"[TRACE:{trace_id}] [fast_path_executor] OK {elapsed_ms}ms "
            f"output=\"{output[:80]}...\"" if len(output) > 80 else f"output=\"{output}\""
        )

        return {
            "messages": [AIMessage(content=output)],
            "final_output": output,
            "fast_path_result": output,
            "processing_path": "fast",
            "collected_data_summary": result,
        }

    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"[TRACE:{trace_id}] [fast_path_executor] ERROR {elapsed_ms}ms error={e}")
        error_msg = f"查询失败：{e}。请稍后重试或联系管理员。"
        return {
            "messages": [AIMessage(content=error_msg)],
            "final_output": error_msg,
            "processing_path": "degraded",
        }


# =============================================================================
# API Query Functions
# =============================================================================


async def _query_spanloss(params: dict) -> str:
    """Query fiber spanloss and apply threshold judgment."""
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0, f"Invalid fiber_id: {fiber_id}"

    resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/spanloss")
    data = json.loads(resp)

    if data.get("error"):
        return f"错误: {data.get('message', 'Unknown error')}"

    spanloss = data.get("spanloss", data.get("data", {}).get("spanloss"))
    if spanloss is not None:
        spanloss = float(spanloss)
        if spanloss > SPANLOSS_CRITICAL:
            status = "⚠️ 严重超标，建议立即检修"
        elif spanloss > SPANLOSS_THRESHOLD:
            status = "⚡ 超过阈值，建议关注"
        else:
            status = "✅ 正常"
        return f"spanloss={spanloss}, status={status}"

    return json.dumps(data, ensure_ascii=False)[:500]


async def _query_connection(params: dict) -> str:
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0
    resp = await fiber_http_client.get(f"/api/v1/topology/fibers/{fiber_id}")
    return _truncate_response(resp)


async def _query_performance(params: dict) -> str:
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0
    if params.get("history"):
        resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/performance/history")
    else:
        resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/performance")
    return _truncate_response(resp)


async def _query_fiber_alarm(params: dict) -> str:
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0
    resp = await fiber_http_client.get(f"/api/v1/topology/fibers/{fiber_id}")
    return _truncate_response(resp)


async def _query_port_alarm(params: dict) -> str:
    board_id = params.get("board_id")
    port_id = params.get("port_id")
    assert isinstance(board_id, int) and board_id > 0
    assert isinstance(port_id, int) and port_id > 0
    resp = await fiber_http_client.get(
        "/api/v1/alarms/current", params={"board_id": board_id, "port_id": port_id}
    )
    return _truncate_response(resp)


async def _query_colored(params: dict) -> str:
    color = params.get("color", "RED")
    assert color in ("RED", "YELLOW", "GREEN"), f"Invalid color: {color}"
    resp = await fiber_http_client.get("/api/v1/fibers/colored", params={"color": color})
    return _truncate_response(resp)


async def _query_stats(params: dict) -> str:
    resp = await fiber_http_client.get("/api/v1/fibers/stats")
    return _truncate_response(resp)


async def _query_trend(params: dict) -> str:
    resp = await fiber_http_client.get("/api/v1/fibers/stats/trend")
    return _truncate_response(resp)


async def _query_fiber_status(params: dict) -> str:
    fiber_id = params.get("fiber_id")
    if fiber_id:
        resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/spanloss")
        return _truncate_response(resp)
    return "未指定光纤ID"


# =============================================================================
# Template Rendering
# =============================================================================


def _render_template(template_id: str, params: dict, data: str) -> str:
    """Render output using predefined template."""
    template = TEMPLATES.get(template_id, "{data}")

    # Determine status for spanloss
    status = ""
    if "spanloss=" in data:
        if "严重超标" in data:
            status = "状态：严重超标 ⚠️"
        elif "超过阈值" in data:
            status = "状态：偏高 ⚡"
        elif "正常" in data:
            status = "状态：正常 ✅"

    try:
        color_cn = {"RED": "红色", "YELLOW": "黄色", "GREEN": "绿色"}.get(
            params.get("color", ""), ""
        )
        return template.format(
            fiber_id=params.get("fiber_id", ""),
            board_id=params.get("board_id", ""),
            port_id=params.get("port_id", ""),
            color=color_cn,
            spanloss=data.split("spanloss=")[1].split(",")[0] if "spanloss=" in data else "",
            threshold=SPANLOSS_THRESHOLD,
            status=status or data[:200],
            data=data[:500],
        )
    except (KeyError, IndexError):
        return data[:500]


def _truncate_response(resp: str, max_len: int = 500) -> str:
    """Truncate API response for display."""
    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown')}"
        return json.dumps(data, ensure_ascii=False)[:max_len]
    except json.JSONDecodeError:
        return resp[:max_len]
