"""
Analysis Expert Node — ReAct Loop reasoning (qwen2.5:14b).

Uses primary LLM (14b) for analysis reasoning:
- Decides whether more data is needed (Loop control)
- Generates structured AnalysisVerdict
- Implements no-progress detection via action_signature
- Records LoopRecord for audit trail

This is the "brain" of the Controlled Loop.
"""

from __future__ import annotations

import logging
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate

from ..graph.routing import compute_action_signature
from ..graph.state import AnalysisVerdict, LoopRecord, MainGraphState
from ..llm.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    escape_for_template,
    load_prompt,
)
from ..llm.provider import get_analysis_llm
from ..memory.experience_store import get_experience_store

logger = logging.getLogger(__name__)

# 提示词唯一管理点：prompts/analysis_expert/system.md + user.md（AGENTS.md 约束）

# human 模板兜底（仅 user.md 缺失时使用）
_ANALYSIS_USER_FALLBACK = """## 用户问题
{question}

## 规则判断（程序化，可信）
{rule_judgment}

## 已收集数据摘要
{data_summary}

## 循环历史
{loop_history}

## 该光纤历史经验（确定性检索，仅供参考）
{experience_history}

## 状态: 第 {loop_count}/{max_loops} 轮, LLM调用 {llm_calls}/{max_llm_calls}"""

_USER_KEEP_VARS = (
    "question", "rule_judgment", "data_summary", "loop_history",
    "experience_history", "loop_count", "max_loops", "llm_calls", "max_llm_calls",
)

# Lazy-initialized chain
_analysis_chain = None


def _get_chain():
    global _analysis_chain
    if _analysis_chain is None:
        llm = get_analysis_llm()
        system = escape_for_template(
            load_prompt("analysis_expert", "system", default=ANALYSIS_SYSTEM_PROMPT),
            keep_vars=("loop_count", "max_loops"),
        )
        human = escape_for_template(
            load_prompt("analysis_expert", "user", default=_ANALYSIS_USER_FALLBACK),
            keep_vars=_USER_KEEP_VARS,
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", human),
        ])
        # json_mode: 百炼 thinking 模式拒绝 function_calling 的
        # tool_choice=required，改用 json_mode + 提示词约定 schema。
        _analysis_chain = prompt | llm.with_structured_output(
            AnalysisVerdict, method="json_mode"
        )
    return _analysis_chain


async def analysis_expert_node(state: MainGraphState) -> dict:
    """
    Analysis expert — ReAct Loop reasoning step. Uses 14b model.

    Returns AnalysisVerdict + loop control updates.
    """
    loop_count = state.get("loop_count", 0)
    judgment = state.get("rule_judgment")

    # Build judgment text
    if judgment:
        judgment_text = (
            f"状态: {judgment.get('status', 'UNKNOWN')}\n"
            f"发现: {'; '.join(judgment.get('findings', []))}\n"
            f"指标: {judgment.get('metrics', {})}"
        )
    else:
        judgment_text = "无"

    # Loop history
    history = state.get("loop_history", [])
    if history:
        history_text = "\n".join([
            f"  第{r.get('loop_number', '?')}轮: {r.get('reason', '未说明')}"
            for r in history
        ])
    else:
        history_text = "无"

    # [P1-A] Deterministic experience retrieval (never LLM-triggered)
    store = get_experience_store()
    fiber_key = store.fiber_key_of((state.get("normalized_params") or {}).get("fiber_ids"))
    experiences = store.query(fiber_key) if fiber_key else []
    if experiences:
        experience_text = "\n".join([
            f"  - [{e['severity']}] {e['conclusion']} ({e['created_at'][:10]})"
            for e in experiences
        ])
    else:
        experience_text = "无"

    try:
        chain = _get_chain()
        verdict: AnalysisVerdict = await chain.ainvoke({
            "question": state.get("user_input", ""),
            "rule_judgment": judgment_text,
            "data_summary": state.get("collected_data_summary", "暂无"),
            "loop_history": history_text,
            "experience_history": experience_text,
            "loop_count": loop_count,
            "max_loops": state.get("max_loops", 3),
            "llm_calls": state.get("llm_call_count", 0),
            "max_llm_calls": state.get("max_llm_calls", 10),
        })

        updates: dict = {
            "analysis_verdict": verdict.model_dump(),
            "llm_call_count": state.get("llm_call_count", 0) + 1,
        }

        # No-progress detection (enhanced Loop audit trail)
        if verdict.need_more_data and verdict.additional_query:
            action_sig = compute_action_signature(
                str(verdict.additional_query),
                (state.get("collected_data_summary", "") or "")[:500],
            )
            if action_sig == state.get("last_action_signature"):
                updates["no_progress_count"] = state.get("no_progress_count", 0) + 1
            else:
                updates["no_progress_count"] = 0
                updates["last_action_signature"] = action_sig

            # Record audit (enhanced LoopRecord)
            record = LoopRecord(
                loop_number=loop_count + 1,
                reason=verdict.additional_query.get("reason", "未说明"),
                tool_requested=verdict.additional_query.get("tool", "unknown"),
                action_signature=action_sig,
                timestamp=datetime.now().isoformat(),
            )
            updates["loop_history"] = [record.model_dump()]
            updates["loop_count"] = loop_count + 1

        logger.info(
            f"[AnalysisExpert] verdict: severity={verdict.severity}, "
            f"need_more={verdict.need_more_data}, confidence={verdict.confidence}"
        )

        # [P1-A] Deterministic experience write: WARNING/CRITICAL only.
        # Same dedup philosophy as color-change snapshots; the LLM never
        # decides whether to persist memory.
        if verdict.severity in ("WARNING", "CRITICAL") and fiber_key:
            try:
                store.save(
                    fiber_key,
                    verdict.severity,
                    verdict.conclusion,
                    verdict.evidence,
                )
            except Exception as e:  # noqa: BLE001 - memory must never break analysis
                logger.warning(f"[AnalysisExpert] Experience save failed: {e}")

        return updates

    except Exception as e:
        logger.error(f"[AnalysisExpert] LLM failed: {e}")
        # Fallback: use rule judgment directly, no more data needed
        fallback_verdict = AnalysisVerdict(
            conclusion="分析服务暂时不可用，基于规则判断输出结果",
            severity=judgment.get("status", "NORMAL") if judgment else "NORMAL",
            evidence=judgment.get("findings", []) if judgment else [],
            confidence=0.5,
            need_more_data=False,
        )
        return {
            "analysis_verdict": fallback_verdict.model_dump(),
            "llm_call_count": state.get("llm_call_count", 0) + 1,
            "degradation_level": max(state.get("degradation_level", 0), 1),
        }
