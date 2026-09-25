"""
Rubric LLM 评判器（书籍 Ch6：确定性检查先行、LLM 评判其后）。

【定位】
- 仅对确定性检查全部通过的用例进行软维度评判
- 评判维度：事实准确性 / 完整性 / 合规性 / 表达质量（各 1-4 分）
- 幻觉不在此处判断（已由 checks.check_numbers 硬性 veto）

【裁判模型】
- 环境变量 EVAL_JUDGE_MODEL/EVAL_JUDGE_API_BASE/EVAL_JUDGE_API_KEY，支持异源裁判
- 已知限制：默认回退到系统 primary（qwen 系）同家族，非严格异源评判；
  缓解 = 确定性硬门先行，LLM 仅评软维度。配置 EVAL_JUDGE_* 后可切换异源
- Key 缺失时自动跳过（返回 None），不阻塞评估
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

RUBRIC_PROMPT = """你是光纤维护 Agent 输出的质量评审员。按 Rubric 给分，每项 1-4 分：
- factual_accuracy 事实准确性：结论是否基于给定数据，无夸大无编造
- completeness 完整性：是否回答了用户问题的全部要点
- compliance 合规性：结论严重级别是否与规则判断一致，建议是否可操作
- expression 表达质量：语言是否清晰专业

只评判提供的信息，缺失信息按 2 分处理。

## 输入
用户问题：{question}
最终输出：
{output}
数据摘要：
{data_summary}
规则判断：
{rule_judgment}

## 输出格式（严格 JSON，不要其他内容）
{{"factual_accuracy": <1-4>, "completeness": <1-4>, "compliance": <1-4>,
 "expression": <1-4>, "evidence": "<一句话总评>"}}"""

_DIMENSIONS = ("factual_accuracy", "completeness", "compliance", "expression")


class RubricJudge:
    """LLM Rubric 评判器（支持异源裁判，懒初始化）."""

    def __init__(self, model: Optional[str] = None):
        self._model = model or os.environ.get("EVAL_JUDGE_MODEL", "qwen3-max")
        self._llm = None

    @property
    def available(self) -> bool:
        """异源 Key 或系统 Key，二者任一配置完整即可用."""
        judge_key = os.environ.get("EVAL_JUDGE_API_KEY")
        if judge_key:
            return True
        from src.config import OPENAI_API_KEY

        return bool(OPENAI_API_KEY)

    def _get_llm(self):
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            # 优先异源裁判通道（EVAL_JUDGE_*），缺失回退到系统 OPENAI_*
            judge_base = os.environ.get("EVAL_JUDGE_API_BASE")
            judge_key = os.environ.get("EVAL_JUDGE_API_KEY")

            if judge_base and judge_key:
                base_url = judge_base
                api_key = judge_key
            else:
                from src.config import OPENAI_API_BASE, OPENAI_API_KEY

                base_url = OPENAI_API_BASE
                api_key = OPENAI_API_KEY

            self._llm = ChatOpenAI(
                model=self._model,
                temperature=0.0,
                base_url=base_url,
                api_key=api_key,
                timeout=60,
                max_retries=1,
            )
        return self._llm

    async def judge(self, case: dict, state: dict) -> Optional[dict]:
        """对单条用例的最终输出做 Rubric 评判.

        【返回值】各维度分数 + evidence 的字典；不可用或解析失败返回 None。
        """
        if not self.available:
            logger.info("[RubricJudge] Skipped: no API key configured")
            return None
        try:
            from langchain_core.messages import HumanMessage

            prompt = RUBRIC_PROMPT.format(
                question=case.get("input", ""),
                output=(state.get("final_output") or "")[:2000],
                data_summary=(state.get("collected_data_summary") or "暂无")[:800],
                rule_judgment=str(state.get("rule_judgment") or "无")[:400],
            )
            response = await self._get_llm().ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)

            start, end = content.find("{"), content.rfind("}")
            if start < 0 or end <= start:
                return None
            data = json.loads(content[start : end + 1])
            scores = {d: int(data.get(d, 2)) for d in _DIMENSIONS}
            scores["evidence"] = str(data.get("evidence", ""))[:200]
            return scores
        except Exception as e:  # noqa: BLE001 - 评判失败不阻塞评估
            logger.warning(f"[RubricJudge] Failed: {e}")
            return None
