"""
数据采集节点 — ReAct Agent + ToolNode [v7.1]。

这是唯一绑定后端 API 工具的组件（P2 原则）。
内部使用 create_react_agent 实现自动工具调用循环。

从 MainGraphState 接收上下文：
- user_input、normalized_params、intent → 构建针对性的采集提示词
- analysis_verdict.additional_query → ReAct 循环补充采集

返回：
- collected_data_summary: 供 rule_judgment / analysis 使用的精简数据
- messages: 工具调用轨迹（追加）
- llm_call_count: 自增
"""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage

from ...llm.provider import get_data_collector_llm
from ...tools import DATA_COLLECTOR_TOOLS

logger = logging.getLogger(__name__)

# =============================================================================
# 数据采集系统提示词
# =============================================================================

DATA_COLLECTOR_SYSTEM = """你是光纤维护系统的数据采集员。
你的唯一职责是调用工具获取光纤数据，不做分析判断。

## 规则
1. 根据用户需求调用合适的工具获取数据
2. 光纤 ID 为整数（如 1, 2, 3），直接使用
3. 获取所有相关数据（拓扑、性能、衰耗、告警）
4. 如果某个查询失败，报告错误但继续其他查询
5. 最终输出所有获取到的原始数据摘要（JSON 格式）
6. 不要编造数据，不要做分析判断

## 输出格式
收集完数据后，输出一个 JSON 摘要：
{"collected": [{"tool": "工具名", "params": {...}, "result_summary": "关键数据"}], "errors": [...]}
"""


def _build_collection_prompt(state: dict) -> str:
    """
    根据 MainGraphState 上下文构建有针对性的数据采集提示词。

    同时处理初次采集与 ReAct 循环中的补充采集。
    """
    parts = []

    # 检查是否为 analysis_expert 发起的补充采集请求
    verdict = state.get("analysis_verdict")
    if verdict and isinstance(verdict, dict):
        additional = verdict.get("additional_query")
        if additional and isinstance(additional, dict):
            reason = additional.get("reason", "补充数据")
            tool = additional.get("tool", "")
            params = additional.get("params", {})
            parts.append(f"## 补充数据采集（第 {state.get('loop_count', 0) + 1} 轮）")
            parts.append(f"原因：{reason}")
            if tool:
                parts.append(f"建议工具：{tool}")
            if params:
                parts.append(f"参数：{json.dumps(params, ensure_ascii=False)}")
            parts.append("")

    # 用户的原始请求
    user_input = state.get("user_input", "")
    if user_input:
        parts.append(f"## 用户请求\n{user_input}")

    # 归一化参数
    params = state.get("normalized_params")
    if params and isinstance(params, dict):
        param_desc = []
        if params.get("fiber_ids"):
            param_desc.append(f"光纤ID: {params['fiber_ids']}")
        if params.get("board_ids"):
            param_desc.append(f"板卡ID: {params['board_ids']}")
        if params.get("port_ids"):
            param_desc.append(f"端口ID: {params['port_ids']}")
        if params.get("color"):
            param_desc.append(f"颜色: {params['color']}")
        if params.get("start_time"):
            param_desc.append(f"起始时间: {params['start_time']}")
        if params.get("end_time"):
            param_desc.append(f"结束时间: {params['end_time']}")
        if param_desc:
            parts.append("## 已解析参数\n" + "\n".join(param_desc))

    # 意图提示
    intent = state.get("intent", "")
    if intent:
        parts.append(f"## 意图类型\n{intent}")

    parts.append("\n请调用工具获取数据。")
    return "\n\n".join(parts)


async def data_collector_subgraph(state: dict) -> dict:
    """
    数据采集器节点：带后端 API 工具的 ReAct Agent。

    架构说明：
    - LLM：qwen2.5:14b，temperature=0.0（工具调用准确性）
    - 工具：12+ 后端 API 工具（拓扑、性能、告警、着色、统计）
    - 递归上限：10（防止无限工具调用循环）

    该函数封装 create_react_agent 以对接 MainGraphState。
    """
    import time

    from langgraph.prebuilt import create_react_agent

    trace_id = state.get("trace_id", "")
    start_time = time.time()

    prompt_text = _build_collection_prompt(state)
    logger.info(f"[TRACE:{trace_id}] [data_collector] START prompt_len={len(prompt_text)} chars")

    try:
        llm = get_data_collector_llm()

        # 构建 ReAct Agent
        agent = create_react_agent(
            model=llm,
            tools=DATA_COLLECTOR_TOOLS,
            prompt=DATA_COLLECTOR_SYSTEM,
        )

        # 使用聚焦消息调用
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=prompt_text)]},
            config={"recursion_limit": 10},
        )

        # 提取最终的 AI 回答作为数据摘要
        messages = result.get("messages", [])
        data_summary = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                data_summary = msg.content
                break

        if not data_summary:
            data_summary = "数据采集未返回有效结果。"

        # 截断以防止状态膨胀
        if len(data_summary) > 3000:
            data_summary = data_summary[:3000] + "\n...(数据已截断)"

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(f"[TRACE:{trace_id}] [data_collector] OK {elapsed_ms}ms " f"summary_len={len(data_summary)} chars")

        return {
            "collected_data_summary": data_summary,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
            "audit_trail": [
                {
                    "node": "data_collector",
                    "action": "tool_collection",
                    "tools_available": len(DATA_COLLECTOR_TOOLS),
                    "summary_length": len(data_summary),
                }
            ],
        }

    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"[TRACE:{trace_id}] [data_collector] ERROR {elapsed_ms}ms error={e}")
        error_msg = f"数据采集失败：{e}"
        return {
            "collected_data_summary": error_msg,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
            "audit_trail": [
                {
                    "node": "data_collector",
                    "action": "error",
                    "error": str(e),
                }
            ],
        }
