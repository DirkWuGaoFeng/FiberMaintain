"""
叙述员节点 —— LLM 文本表达（使用 qwen2.5:7b 副模型）。

【功能说明】
叙述员的唯一职责：将结构化判断转换为自然语言。
它有严格的硬约束：
- 不得修改任何数值（如 3.2dB 不能写成“约3dB”）
- 不得添加判断中没有的结论
- 不得编造数据
- 不得改变严重程度级别

【架构位置】
  分析专家/规则判断 → 【叙述员】 → 叙述校验器

【面试知识点】
  Q: 为什么用 7b 而不是 14b？
  A: 叙述员只做文本转换，不需要复杂推理能力。
     7b 模型延迟更低、成本更低，足够胜任表达任务。

  Q: 为什么需要叙述校验器？
  A: 即使有硬约束，LLM 仍可能在数字上产生幻觉。
     校验器会比对原始数值和输出数值，发现不一致时触发兆底。
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from ..governance.number_validator import validate_narration_numbers
from ..graph.state import MainGraphState
from ..llm.provider import get_narrator_llm

logger = logging.getLogger(__name__)

# 叙述员提示词（已是中文）
NARRATOR_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是光纤维护报告的叙述员。

## 你的唯一职责
将以下【结构化判断】转换为通顺的自然语言回答。

## 硬约束（违反任何一条即为失败）
1. 不得修改任何数值（如 3.2dB 不能写成"约3dB"）
2. 不得添加判断中没有的结论
3. 不得编造数据
4. 不得改变严重程度判断（NORMAL/WARNING/CRITICAL）
5. 可以调整语序、增加连接词、使表述更自然

## 输出格式
直接用自然语言回答用户问题，200字以内。""",
        ),
        (
            "human",
            """## 用户问题
{question}

## 结构化判断（不可修改）
状态: {status}
发现:
{findings}
关键指标: {metrics}
建议操作: {actions}

请将以上判断转换为自然语言回答。""",
        ),
    ]
)

# 懒加载的叙述链（首次调用时初始化）
_narrator_chain = None


def _get_chain():
    """获取叙述链（懒加载单例）。"""
    global _narrator_chain
    if _narrator_chain is None:
        _narrator_chain = NARRATOR_PROMPT | get_narrator_llm()
    return _narrator_chain


async def narrator_node(state: MainGraphState) -> dict:
    """叙述员节点 —— 将结构化判断转为自然语言（使用 7b 副模型）。

    【输入】
        state: 主图状态，包含 rule_judgment

    【输出】
        包含 narration、final_output 的状态字典

    【核心逻辑】
    1. 调用 LLM 将结构化判断转为自然语言
    2. 数字幻觉校验（比对原始数值和输出数值）
    3. 校验失败时降级到模板输出

    【面试知识点】
    这是「防幻觉」设计的关键一环：
    叙述员 → 校验器 → 兆底模板，三层防护确保数值准确。
    """
    judgment = state.get("rule_judgment")

    if not judgment:
        fallback_msg = "暂无分析结果。"
        return {
            "messages": [AIMessage(content=fallback_msg)],
            "narration": fallback_msg,
            "final_output": fallback_msg,
        }

    try:
        chain = _get_chain()
        response = await chain.ainvoke(
            {
                "question": state.get("user_input", ""),
                "status": judgment.get("status", "UNKNOWN"),
                "findings": "\n".join(f"  • {f}" for f in judgment.get("findings", [])),
                "metrics": str(judgment.get("metrics", {})),
                "actions": "、".join(judgment.get("suggested_actions", [])) or "无",
            }
        )

        narration = response.content if hasattr(response, "content") else str(response)

        # 数字幻觉校验 [governance]
        # 【设计意图】比对 LLM 输出中的数值与原始判断中的数值
        source_numbers = dict(judgment.get("metrics", {}))
        hallucination_errors = validate_narration_numbers(narration, source_numbers)
        if hallucination_errors:
            logger.warning(f"[Narrator] 检测到数字幻觉: {hallucination_errors}")
            # 降级到模板输出（不使用 LLM 结果）
            findings = judgment.get("findings", [])
            status = judgment.get("status", "UNKNOWN")
            narration = f"📊 光纤状态：{status}\n" + "\n".join(f"  • {f}" for f in findings)

        return {
            "messages": [AIMessage(content=narration)],
            "narration": narration,  # [v7.1] 保存供校验器使用
            "final_output": narration,
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }

    except Exception as e:
        logger.error(f"[Narrator] LLM failed: {e}, using template fallback")
        # 兜底：简单的模板输出
        findings = judgment.get("findings", [])
        status = judgment.get("status", "UNKNOWN")
        fallback = f"📊 光纤状态：{status}\n" + "\n".join(f"  • {f}" for f in findings)
        return {
            "messages": [AIMessage(content=fallback)],
            "narration": fallback,
            "final_output": fallback,
            "degradation_level": max(state.get("degradation_level", 0), 1),
        }
