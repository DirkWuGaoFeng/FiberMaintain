"""
澄清交互节点 —— 参数不完整时向用户追问。

【功能说明】
当 ParamGate 检测到 parse_failures 时，生成友好的追问消息，
引导用户补充缺失的参数。

【设计说明】
使用 LangGraph 原生 interrupt() 暂停图执行。
用户回复后通过 Command(goto="rule_engine") 恢复。

优势：
- 状态由 Checkpointer 持久化，服务重启后不丢失
- 恢复时跳过 input_guard（已验证过）
- 用户回复也可以命中规则引擎

【面试知识点】
  Q: 为什么追问后要回到规则引擎而不是直接处理？
  A: 用户补充的信息可能改变意图判断，重新走规则引擎可以保证一致性。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)

# 意图级追问提示词：针对性引导用户补充缺失参数
_INTENT_CLARIFICATION: dict[str, str] = {
    "spanloss_query": "请告诉我您要查询哪根光纤的衰耗，例如：",
    "spanloss_analysis": "请告诉我您要分析哪根光纤的衰耗，例如：",
    "connection_query": "请告诉我您要查询哪根光纤的连纤，例如：",
    "performance_query": "请告诉我您要查询哪根光纤的性能，例如：",
    "fiber_alarm_query": "请告诉我您要查询哪根光纤的告警，例如：",
    "single_query": "请告诉我您要查询哪根光纤，例如：",
    "trend_analysis": "请告诉我您要分析哪根光纤的趋势，例如：",
    "color_diagnosis": "请告诉我您要诊断哪根光纤的颜色状态，例如：",
    "port_alarm_query": "请告诉我您要查询哪个端口的告警，例如：",
}


async def clarification_node(state: MainGraphState) -> dict:
    """澄清节点：向用户追问缺失的参数。

    【功能说明】
    当 ParamGate 检测到 parse_failures 时，生成包含示例的追问消息，
    帮助用户理解正确的输入格式。

    【输入】state.normalized_params.parse_failures（解析失败列表）
    【输出】final_output（追问消息文本）
    """
    params = state.get("normalized_params", {})
    failures = params.get("parse_failures", [])
    intent = state.get("intent", "")

    # 构建追问消息：根据意图生成针对性提示
    question_parts = []

    # 意图级针对性追问
    if intent in _INTENT_CLARIFICATION:
        question_parts.append(_INTENT_CLARIFICATION[intent])
    else:
        question_parts.append("抱歉，以下信息我没能正确识别：")

    # 附加具体失败原因
    if failures:
        for f in failures:
            question_parts.append(f"  • {f}")

    clarification_msg = "\n".join(question_parts)

    logger.info(f"[Clarification] intent={intent} failures={len(failures)}")

    # MVP 阶段：将追问消息作为最终输出返回
    # 生产环境支持 interrupt 时，将使用：
    #   user_reply = interrupt({"question": clarification_msg})
    #   return Command(goto="rule_engine", update={"user_input": user_reply})
    return {
        "messages": [AIMessage(content=clarification_msg)],
        "final_output": clarification_msg,
        "processing_path": "clarification",
    }
