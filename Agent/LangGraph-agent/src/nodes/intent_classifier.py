"""
意图分类器节点 —— LLM 意图识别（使用 qwen2.5:14b 主模型）。

【功能说明】
当规则引擎未命中时（约 22% 的查询），由本节点使用 LLM 识别用户意图。
使用 with_structured_output 强制输出 IntentResult 结构化 JSON。

【架构位置】
  规则引擎未命中 → 【意图分类器】 → 参数门禁

【面试知识点】
  Q: 为什么规则引擎未命中时才用 LLM？
  A: LLM 调用延迟约 1-2s，而规则引擎 <10ms。
     78% 的查询可以被规则引擎命中，大幅节省 LLM 成本。

  Q: 什么是 with_structured_output？
  A: LangChain 的方法，强制 LLM 输出符合 Pydantic 模型的 JSON。
     支持 function_calling 和 json_mode 两种实现。
"""

from __future__ import annotations

import logging

from langchain_core.prompts import ChatPromptTemplate

from ..graph.state import IntentResult, MainGraphState
from ..llm.prompts import (
    INTENT_CLASSIFIER_PROMPT,
    escape_for_template,
    load_prompt,
)
from ..llm.provider import get_intent_llm

logger = logging.getLogger(__name__)

# 提示词唯一管理点：prompts/lead_agent/intent_classifier.md（AGENTS.md 约束）

# 懒加载的意图分类链（首次调用时初始化）
_intent_chain = None


def _get_chain():
    """获取意图分类链（懒加载单例）。"""
    global _intent_chain
    if _intent_chain is None:
        llm = get_intent_llm()
        system = escape_for_template(load_prompt("lead_agent", "intent_classifier", default=INTENT_CLASSIFIER_PROMPT))
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                # 对话历史上下文（可选，为空时不显示）
                ("human", "{context}"),
                ("human", "用户输入：{user_input}"),
            ]
        )
        # json_mode: 百炼 thinking 模式拒绝 function_calling 的
        # tool_choice=required，改用 json_mode + 提示词约定 schema。
        _intent_chain = prompt | llm.with_structured_output(IntentResult, method="json_mode")
    return _intent_chain


async def intent_classifier_node(state: MainGraphState) -> dict:
    """意图分类节点（使用 14b 主模型）。

    【输入】
        state: 主图状态，包含 user_input 和 messages（对话历史）

    【输出】
        包含 intent、intent_result、llm_call_count 的状态字典

    【多轮对话上下文】
    从 state["messages"] 提取最近 3 条对话历史，注入 LLM 提示词，
    使 LLM 能理解用户的补充回复（如 "光纤3" 是对追问的回答）。

    【降级策略】
    LLM 调用失败时，降级为 chitchat 意图，避免系统崩溃。
    """
    import time

    user_input = state.get("user_input", "")
    trace_id = state.get("trace_id", "")
    start_time = time.time()

    logger.info(f'[TRACE:{trace_id}] [intent_classifier] START input="{user_input[:80]}"')

    # 提取对话历史上下文（最近 3 条，排除当前输入）
    context = _build_context_from_messages(state.get("messages", []))

    try:
        chain = _get_chain()
        result: IntentResult = await chain.ainvoke(
            {
                "user_input": user_input,
                "context": context,
            }
        )
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(
            f"[TRACE:{trace_id}] [intent_classifier] OK {elapsed_ms}ms "
            f"intent={result.intent} confidence={result.confidence}"
        )
        return {
            "intent": result.intent,
            "intent_result": result.model_dump(),
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }
    except Exception as e:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"[TRACE:{trace_id}] [intent_classifier] ERROR {elapsed_ms}ms error={e}")
        # 失败时降级为 chitchat 意图
        return {
            "intent": "chitchat",
            "intent_result": IntentResult(intent="chitchat", confidence=0.0).model_dump(),
            "degradation_level": max(state.get("degradation_level", 0), 1),
        }


def _build_context_from_messages(messages: list, max_messages: int = 3) -> str:
    """从消息列表构建对话历史上下文。

    【功能说明】
    提取最近 N 条消息作为对话历史，注入 LLM 提示词。
    如果历史为空或只有当前输入，返回空字符串。

    【参数说明】
        messages: state 中的消息列表（包含当前输入）
        max_messages: 最多提取的消息数量

    【返回值】
        格式化的对话历史字符串，或空字符串
    """
    if not messages:
        return ""

    # 排除当前用户输入（最后一条 HumanMessage）
    history = []
    for msg in messages[:-1]:
        role = "用户" if hasattr(msg, "type") and msg.type == "human" else "助手"
        content = msg.content if hasattr(msg, "content") else str(msg)
        if content:
            history.append(f"{role}：{content[:100]}")  # 截断过长内容

    if not history:
        return ""

    # 取最近 N 条
    recent = history[-max_messages:]
    return "对话历史：\n" + "\n".join(recent)
