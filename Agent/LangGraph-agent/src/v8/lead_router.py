"""
Lead Router — 场景解析与任务分派.

策略：规则优先 + LLM 兜底
1. 遍历已加载的 Skill YAML trigger 规则 → 精确匹配
2. 未命中 → 3b LLM 分类（结构化输出 + 白名单校验）
3. 仍未命中 → default_skill 兜底

输出：ExecutionPlan（驱动三层 Agent）

安全加固：
- LLM 输出必须通过白名单校验（已注册 skill ID 集合）
- confidence 由 LLM 自评，下游可消费（< 0.5 触发用户确认）
- 结构化输出协议（消除格式不确定性）
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..skills.loader import get_registries, get_skill_loader
from .models import ExecutionPlan

logger = logging.getLogger(__name__)


# =============================================================================
# LLM 分类结构化输出协议
# =============================================================================


class IntentClassification(BaseModel):
    """LLM 意图分类的结构化输出."""

    intent: str = Field(description="匹配的场景 ID")
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="分类置信度"
    )
    reasoning: str = Field(default="", description="分类理由")


class LeadRouter:
    """场景解析器 — 规则优先 + LLM 兜底 + 白名单校验."""

    def __init__(self):
        self._loader = get_skill_loader()
        registries = get_registries()
        self._trigger_registry = registries["trigger"]
        self._routing_registry = registries["routing"]
        # 白名单：所有已注册的 skill ID
        self._skill_whitelist: set[str] = {
            s.id for s in self._loader.all_skills()
        }

    async def resolve(
        self,
        user_input: str,
        normalized_params: dict[str, Any],
        trace_id: str = "",
    ) -> ExecutionPlan:
        """
        解析用户输入 → 生成 ExecutionPlan.

        优先级：
        1. Skill YAML trigger 规则匹配
        2. LLM 意图分类（3b）+ 白名单校验
        3. default_skill 兜底
        """
        # Phase 1: 规则匹配
        plan = self._rule_match(user_input, normalized_params)
        if plan:
            logger.info(
                f"[TRACE:{trace_id}] [LeadRouter] Rule match: "
                f"scenario={plan.scenario_id} confidence={plan.confidence}"
            )
            return plan

        # Phase 2: LLM 分类（结构化 + 白名单）
        plan = await self._llm_classify(user_input, trace_id)
        if plan:
            logger.info(
                f"[TRACE:{trace_id}] [LeadRouter] LLM classify: "
                f"scenario={plan.scenario_id} confidence={plan.confidence}"
            )
            return plan

        # Phase 3: 兜底
        logger.info(f"[TRACE:{trace_id}] [LeadRouter] Fallback to default")
        return self._default_plan(user_input)

    def _rule_match(
        self, user_input: str, params: dict[str, Any]
    ) -> Optional[ExecutionPlan]:
        """Skill YAML trigger 规则匹配."""
        match = self._trigger_registry.match(user_input)
        if not match:
            return None

        intent = match["intent"]
        skill = self._loader.get_skill(intent)
        if not skill:
            # 通过 intent 反查 skill
            for s in self._loader.all_skills():
                if s.routing.intent == intent:
                    skill = s
                    break
        if not skill:
            return None

        return ExecutionPlan(
            scenario_id=skill.id,
            intent=intent,
            confidence=match["confidence"],
            match_type="rule",
            tools=skill.collector_tools,
            judgment_rules=[skill.judgment.metric] if skill.judgment else [],
            threshold_refs=[],
            output_format="narrative",
            output_template=skill.template.fast_path if skill.template else "",
            max_loop_rounds=3,
            skill_metadata={"skill_id": skill.id, "version": skill.version},
        )

    async def _llm_classify(
        self, user_input: str, trace_id: str
    ) -> Optional[ExecutionPlan]:
        """LLM 意图分类（结构化输出 + 白名单校验）."""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            from ..llm.provider import get_intent_llm

            llm = get_intent_llm()
            skills = self._loader.all_skills()
            skill_list = "\n".join(
                f"- {s.id}: {s.description}" for s in skills
            )

            system = (
                "你是意图分类器。根据用户输入选择最匹配的场景。\n"
                f"可选场景：\n{skill_list}\n\n"
                '输出严格 JSON：{"intent": "场景ID", '
                '"confidence": 0.0-1.0, "reasoning": "理由"}\n'
                "如果没有匹配的，intent 设为 \"UNKNOWN\"。"
            )

            response = await llm.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=user_input),
                ]
            )

            content = (
                response.content
                if hasattr(response, "content")
                else str(response)
            )

            # 解析结构化输出
            classification = self._parse_classification(content)
            if not classification:
                return None

            # 白名单校验
            if classification.intent not in self._skill_whitelist:
                logger.warning(
                    f"[TRACE:{trace_id}] [LeadRouter] LLM output "
                    f"'{classification.intent}' not in whitelist, rejecting"
                )
                return None

            # 查找 skill
            skill = self._loader.get_skill(classification.intent)
            if not skill:
                for s in self._loader.all_skills():
                    if s.routing.intent == classification.intent:
                        skill = s
                        break
            if not skill:
                return None

            return ExecutionPlan(
                scenario_id=skill.id,
                intent=skill.routing.intent,
                confidence=classification.confidence,
                match_type="llm",
                tools=skill.collector_tools,
                judgment_rules=[skill.judgment.metric]
                if skill.judgment
                else [],
                threshold_refs=[],
                output_format="narrative",
                max_loop_rounds=3,
            )
        except Exception as e:
            logger.warning(
                f"[TRACE:{trace_id}] [LeadRouter] LLM classify failed: {e}"
            )

        return None

    def _parse_classification(self, content: str) -> Optional[IntentClassification]:
        """解析 LLM 输出为 IntentClassification."""
        # 尝试直接解析 JSON
        json_match = re.search(r"\{[\s\S]*?\}", content)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return IntentClassification(
                    intent=data.get("intent", "UNKNOWN").strip().lower(),
                    confidence=float(data.get("confidence", 0.5)),
                    reasoning=data.get("reasoning", ""),
                )
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Fallback: 正则提取第一个匹配的 skill ID
        content_lower = content.strip().lower()
        for skill_id in self._skill_whitelist:
            if skill_id in content_lower:
                return IntentClassification(
                    intent=skill_id,
                    confidence=0.5,  # 低置信度（格式不确定）
                    reasoning="fallback extraction",
                )

        return None

    def _default_plan(self, user_input: str) -> ExecutionPlan:
        """兜底计划."""
        # 尝试找 group='chitchat' 的 skill 作为默认
        for skill in self._loader.all_skills():
            if skill.routing.group == "chitchat":
                return ExecutionPlan(
                    scenario_id=skill.id,
                    intent=skill.routing.intent,
                    confidence=0.3,
                    match_type="default",
                    tools=skill.collector_tools,
                    output_format="narrative",
                    max_loop_rounds=3,
                )

        return ExecutionPlan(
            scenario_id="fallback",
            intent="general_query",
            confidence=0.1,
            match_type="default",
            tools=["fiber_connection_query", "fiber_performance_query", "alarm_query"],
            output_format="narrative",
        )
