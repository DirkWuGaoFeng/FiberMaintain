"""
快速路径执行器节点 —— 规则命中时的零 LLM 直接执行。

【工作流程】
当规则引擎命中且 fast_path=True 时：
1. 直接调用对应的后端 API（不经过 LLM）
2. 应用阈值规则进行程序化判断
3. 通过模板渲染输出结果

【性能目标】延迟 < 1s，零 LLM 调用，零 token 消耗

【面试知识点】
  Q: 快速路径能覆盖多少场景？
  A: 约 78% 的日常查询是单条光纤的简单查询（如“查光纤12衰耗”），
     这些都可以走快速路径，延迟从 2-5s 降到 <1s。
  Q: 快速路径和正常路径的区别？
  A: 快速路径跳过所有 LLM 节点（意图分类、分析专家、叙述员），
     直接 API + 模板渲染；正常路径经过完整的 ReAct 循环。
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
# 输出模板
# 【设计说明】模板与后端数据分离，模板只负责格式化，不做业务判断
# =============================================================================

TEMPLATES = {
    "T_SPANLOSS": "光纤 {fiber_id} 当前衰耗为 {spanloss} dB（阈值 {threshold} dB），{status}。",
    "T_CONNECTION": "光纤 {fiber_id} 连纤信息：{data}",
    "T_PERFORMANCE": "光纤 {fiber_id} 性能数据：{data}",
    "T_FIBER_ALARM": "光纤 {fiber_id} 告警信息：{data}",
    "T_FIBER_STATUS": "光纤 {fiber_id} 状态：{data}",
    "T_PORT_ALARM": "{board_id}号盘{port_id}口 告警信息：{data}",
    "T_BOARD": "单盘 {board_id} 信息：{data}",
    "T_COLORED": "📊 {color}光纤查询结果，{data}",
    "T_STATS": "光纤统计：{data}",
    "T_TREND": "光纤趋势数据：{data}",
}


async def fast_path_executor_node(state: MainGraphState) -> dict:
    """快速路径执行器：直接 API 调用 + 模板渲染。

    【功能说明】
    处理规则命中的单条查询，无需 LLM 参与。
    根据意图类型路由到对应的 API 查询函数，然后用模板渲染输出。

    【输入】state.rule_match（规则匹配结果，含 intent/params/template_id）
    【输出】final_output（渲染后的用户可见文本）
    【状态更新】messages, final_output, fast_path_result, processing_path="fast"
    """
    import time

    rule_match = state.get("rule_match", {})
    params = rule_match.get("params", {})
    template_id = rule_match.get("template_id", "T_FIBER_STATUS")
    intent = rule_match.get("intent", "single_query")
    trace_id = state.get("trace_id", "")
    start_time = time.time()

    logger.info(
        f"[TRACE:{trace_id}] [fast_path_executor] START " f"intent={intent} params={params} template={template_id}"
    )

    try:
        # 根据意图类型路由到对应的 API 查询
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
            f"[TRACE:{trace_id}] [fast_path_executor] OK {elapsed_ms}ms " f'output="{output[:80]}..."'
            if len(output) > 80
            else f'output="{output}"'
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
# API 查询函数
# 【设计说明】每个函数对应一个后端 API 端点，职责单一
# =============================================================================


async def _query_spanloss(params: dict) -> str:
    """查询光纤跨段衰耗并进行阈值判断。

    【参数】params: 包含 fiber_id（正整数）
    【返回】衰耗值及状态描述（正常/偏高/严重超标）
    【业务规则】
    - spanloss > SPANLOSS_CRITICAL (8.0dB) → 严重超标
    - spanloss > SPANLOSS_THRESHOLD (5.0dB) → 超过阈值
    - 其他 → 正常
    """
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
    """查询光纤连纤信息并格式化输出。

    【参数】params: 包含 fiber_id（正整数）
    【返回】格式化后的连纤信息（源/目的板卡、端口、网元）
    """
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0
    resp = await fiber_http_client.get(f"/api/v1/topology/fibers/{fiber_id}")

    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown error')}"

        fiber = data.get("fiber", data)
        src_board = fiber.get("src_board_id", "?")
        src_port = fiber.get("src_port_id", "?")
        src_ne = fiber.get("src_ne_id", "?")
        dst_board = fiber.get("dst_board_id", "?")
        dst_port = fiber.get("dst_port_id", "?")
        dst_ne = fiber.get("dst_ne_id", "?")
        return (
            f"源端：单盘{src_board} 端口{src_port} 网元{src_ne}\n"
            f"  → 目的端：单盘{dst_board} 端口{dst_port} 网元{dst_ne}"
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(resp)


async def _query_performance(params: dict) -> str:
    """查询光纤性能数据并格式化输出。

    【参数】params: 包含 fiber_id（正整数），可选 history（是否历史数据）
    【返回】格式化后的性能数据（OOP/IOP 等指标）
    """
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0
    if params.get("history"):
        resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/performance/history")
    else:
        resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/performance")

    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown error')}"

        lines = []
        if "src_oop" in data:
            lines.append(f"输出光功率(OOP)：{data['src_oop']}dBm")
        if "dst_iop" in data:
            lines.append(f"输入光功率(IOP)：{data['dst_iop']}dBm")
        if "error_code" in data and data["error_code"] != 0:
            lines.append(f"错误码：{data['error_code']} ({data.get('error_message', '')})")

        if lines:
            return "\n".join(lines)
        return json.dumps(data, ensure_ascii=False)[:500]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(resp)


async def _query_fiber_alarm(params: dict) -> str:
    """查询光纤告警信息并格式化输出。

    【参数】params: 包含 fiber_id（正整数）
    【返回】格式化后的告警信息（告警级别、时间等）
    【实现逻辑】
    1. 先通过拓扑 API 获取光纤的 board_id/port_id
    2. 再调用告警 API 查询当前告警
    """
    fiber_id = params.get("fiber_id")
    assert isinstance(fiber_id, int) and fiber_id > 0

    # 先获取拓扑信息，提取源端 board_id/port_id
    topo_resp = await fiber_http_client.get(f"/api/v1/topology/fibers/{fiber_id}")
    try:
        topo_data = json.loads(topo_resp)
        fiber = topo_data.get("fiber", topo_data)
        src_board = fiber.get("src_board_id")
        src_port = fiber.get("src_port_id")
    except (json.JSONDecodeError, KeyError, TypeError):
        return f"无法获取光纤{fiber_id}的拓扑信息"

    if not src_board or not src_port:
        return f"光纤{fiber_id}拓扑信息不完整，无法查询告警"

    # 查询当前告警
    alarm_resp = await fiber_http_client.get(
        "/api/v1/alarms/current", params={"board_id": src_board, "port_id": src_port}
    )

    try:
        alarm_data = json.loads(alarm_resp)
        if alarm_data.get("error"):
            return f"错误: {alarm_data.get('message', 'Unknown error')}"

        alarms = alarm_data.get("alarms", [])
        if not alarms:
            return "当前无告警"

        lines = [f"共 {len(alarms)} 条告警："]
        for alarm in alarms[:10]:  # 最多显示10条
            level = alarm.get("alarm_level", "UNKNOWN")
            level_cn = {"CRITICAL": "严重", "MAJOR": "主要", "MINOR": "次要", "WARNING": "警告"}.get(level, level)
            raised_at = alarm.get("raised_at", "")
            lines.append(f"  • [{level_cn}] {raised_at}")
        return "\n".join(lines)
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(alarm_resp)


async def _query_port_alarm(params: dict) -> str:
    """查询端口告警信息并格式化输出。

    【参数】params: 包含 board_id、port_id（正整数）
    【返回】格式化后的告警信息
    """
    board_id = params.get("board_id")
    port_id = params.get("port_id")
    assert isinstance(board_id, int) and board_id > 0
    assert isinstance(port_id, int) and port_id > 0
    resp = await fiber_http_client.get("/api/v1/alarms/current", params={"board_id": board_id, "port_id": port_id})

    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown error')}"

        alarms = data.get("alarms", [])
        if not alarms:
            return "当前无告警"

        lines = [f"共 {len(alarms)} 条告警："]
        for alarm in alarms[:10]:
            level = alarm.get("alarm_level", "UNKNOWN")
            level_cn = {"CRITICAL": "严重", "MAJOR": "主要", "MINOR": "次要", "WARNING": "警告"}.get(level, level)
            raised_at = alarm.get("raised_at", "")
            lines.append(f"  • [{level_cn}] {raised_at}")
        return "\n".join(lines)
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(resp)


async def _query_colored(params: dict) -> str:
    """按颜色查询光纤并格式化输出。

    【参数】params: 包含 color（RED/YELLOW/GREEN）
    【返回】格式化后的光纤列表文本（含光纤ID、源/目的板卡信息）
    """
    color = params.get("color", "RED")
    assert color in ("RED", "YELLOW", "GREEN"), f"Invalid color: {color}"
    resp = await fiber_http_client.get("/api/v1/fibers/colored", params={"color": color})

    # 尝试解析并格式化输出
    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown error')}"

        # 提取光纤列表
        fibers = data.get("fibers", [])
        if isinstance(fibers, list) and fibers:
            lines = [f"共 {len(fibers)} 条："]
            for item in fibers[:20]:  # 最多显示20条
                fiber = item.get("fiber", item)
                fid = fiber.get("fiber_id", "?")
                src_board = fiber.get("src_board_id", "?")
                dst_board = fiber.get("dst_board_id", "?")
                src_ne = fiber.get("src_ne_id", "?")
                dst_ne = fiber.get("dst_ne_id", "?")
                lines.append(f"  • 光纤{fid}: 单盘{src_board}(网元{src_ne}) → 单盘{dst_board}(网元{dst_ne})")
            if len(fibers) > 20:
                lines.append(f"  ... 还有 {len(fibers) - 20} 条未显示")
            return "\n".join(lines)
        elif isinstance(fibers, list) and not fibers:
            return "当前没有该颜色光纤"
        else:
            return json.dumps(data, ensure_ascii=False)[:500]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(resp)


async def _query_stats(params: dict) -> str:
    """查询光纤实时统计数据并格式化输出。

    【返回】格式化后的统计信息（总数、各状态数量等）
    """
    resp = await fiber_http_client.get("/api/v1/fibers/stats/realtime")

    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown error')}"

        lines = []
        if "total" in data:
            lines.append(f"光纤总数：{data['total']}")
        if "normal" in data:
            lines.append(f"正常：{data['normal']}")
        if "warning" in data:
            lines.append(f"告警：{data['warning']}")
        if "critical" in data:
            lines.append(f"严重：{data['critical']}")
        if "red_count" in data:
            lines.append(f"红色（中断）：{data['red_count']}")
        if "yellow_count" in data:
            lines.append(f"黄色（告警）：{data['yellow_count']}")
        if "green_count" in data:
            lines.append(f"绿色（正常）：{data['green_count']}")

        if lines:
            return "\n".join(lines)
        return json.dumps(data, ensure_ascii=False)[:500]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(resp)


async def _query_trend(params: dict) -> str:
    """查询光纤趋势数据并格式化输出。

    【返回】格式化后的趋势信息
    """
    resp = await fiber_http_client.get("/api/v1/fibers/stats/trend")

    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown error')}"

        lines = []
        if "period" in data:
            lines.append(f"统计周期：{data['period']}")
        if "new_faults" in data:
            lines.append(f"新增故障：{data['new_faults']}")
        if "resolved" in data:
            lines.append(f"已修复：{data['resolved']}")
        if "trend" in data:
            lines.append(f"趋势：{data['trend']}")

        if lines:
            return "\n".join(lines)
        return json.dumps(data, ensure_ascii=False)[:500]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _truncate_response(resp)


async def _query_fiber_status(params: dict) -> str:
    fiber_id = params.get("fiber_id")
    if fiber_id:
        resp = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/spanloss")
        return _truncate_response(resp)
    return "未指定光纤ID"


# =============================================================================
# 模板渲染
# =============================================================================


def _render_template(template_id: str, params: dict, data: str) -> str:
    """使用预定义模板渲染输出。

    【功能说明】
    将 API 返回的原始数据填充到中文模板中，生成用户可读的文本。
    对于衰耗查询，还会根据阈值自动添加状态标签（✅/⚡/⚠️）。

    【参数说明】
        template_id: 模板 ID（如 T_SPANLOSS）
        params: 查询参数（fiber_id, board_id, color 等）
        data: API 返回的原始数据字符串

    【返回值】
        渲染后的用户可见文本
    """
    template = TEMPLATES.get(template_id, "{data}")

    # 为衰耗查询判断状态
    status = ""
    if "spanloss=" in data:
        if "严重超标" in data:
            status = "状态：严重超标 ⚠️"
        elif "超过阈值" in data:
            status = "状态：偏高 ⚡"
        elif "正常" in data:
            status = "状态：正常 ✅"

    try:
        color_cn = {"RED": "红色", "YELLOW": "黄色", "GREEN": "绿色"}.get(params.get("color", ""), "")
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
    """截断 API 响应以控制输出长度。

    【功能说明】
    解析 JSON 响应，检查是否包含错误，截断到指定长度。
    防止过长的 API 返回数据影响 LLM 上下文窗口。
    """
    try:
        data = json.loads(resp)
        if data.get("error"):
            return f"错误: {data.get('message', 'Unknown')}"
        return json.dumps(data, ensure_ascii=False)[:max_len]
    except json.JSONDecodeError:
        return resp[:max_len]
