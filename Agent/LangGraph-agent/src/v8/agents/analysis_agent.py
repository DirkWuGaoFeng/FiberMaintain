"""
Analysis Agent — 分析判断层.

职责：
1. 规则判断（ThresholdEngine）— 确定性结论
2. LLM 深度分析 — 仅当规则无法覆盖时
3. 决定是否追加采集（needs_more_data 信号）

契约：
- 输入：CollectionPayload（typed schema）
- 输出：AnalysisVerdict（typed schema）
- 规则优先：能用规则判断的不调 LLM
- 阈值从 ThresholdEngine 获取
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ...governance.threshold_engine import get_threshold_engine
from ..contracts import AnalysisVerdict, CollectionPayload, Finding, FiberMetrics
from ..models import AgentLayer, AgentResult, ExecutionPlan
from .base import BaseAgent

logger = logging.getLogger(__name__)


class AnalysisAgent(BaseAgent):
    """分析判断 Agent — 规则优先 + LLM 兜底."""

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.ANALYSIS

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        trace_id = context.get("trace_id", "")
        collection_data = context.get("collection_data", {})

        # 尝试解析为 typed CollectionPayload
        payload = self._parse_payload(collection_data)

        # Phase 1: 规则判断（优先使用结构化数据）
        verdict = self._rule_judgment_typed(payload, plan)

        # 规则已给出明确结论 → 直接返回
        if verdict.status != "UNKNOWN" and plan.analysis_mode != "llm_only":
            return AgentResult(
                layer=self.layer,
                success=True,
                data={
                    "verdict": verdict.model_dump(),
                    "analysis_mode": "rule",
                },
            )

        # Phase 2: LLM 深度分析（规则无法覆盖）
        llm_result = await self._llm_analysis(payload, plan, context)
        return llm_result

    def _parse_payload(self, collection_data: dict) -> CollectionPayload:
        """将 collection_data 解析为 typed CollectionPayload."""
        if isinstance(collection_data, CollectionPayload):
            return collection_data
        try:
            return CollectionPayload.model_validate(collection_data)
        except Exception:
            # 兼容旧格式：只有 raw_summary 字符串
            return CollectionPayload(
                raw_summary=collection_data.get("raw_summary", ""),
                collection_mode="react",
            )

    def _rule_judgment_typed(
        self, payload: CollectionPayload, plan: ExecutionPlan
    ) -> AnalysisVerdict:
        """程序化规则判断 — 优先使用结构化数据."""
        engine = get_threshold_engine()
        findings: list[Finding] = []
        status = "NORMAL"

        # 结构化路径：直接读取 typed metrics
        if payload.has_structured_data:
            for m in payload.metrics:
                if m.spanloss_db is not None:
                    jr = engine.judge_spanloss(m.spanloss_db)
                    findings.append(Finding(
                        metric_name="spanloss",
                        value=m.spanloss_db,
                        unit="dB",
                        level=jr.status,
                        description=f"跨段损耗 {m.spanloss_db}dB → {jr.status}",
                    ))
                    if jr.status == "CRITICAL":
                        status = "CRITICAL"
                    elif jr.status == "WARNING" and status != "CRITICAL":
                        status = "WARNING"

                if m.oop_dbm is not None:
                    level = engine.judge_oop(m.oop_dbm)
                    if level != "NORMAL":
                        findings.append(Finding(
                            metric_name="oop",
                            value=m.oop_dbm,
                            unit="dBm",
                            level=level,
                            description=f"出光功率 {m.oop_dbm}dBm → {level}",
                        ))
                        if level == "CRITICAL":
                            status = "CRITICAL"
                        elif status != "CRITICAL":
                            status = "WARNING"

                if m.iop_dbm is not None:
                    level = engine.judge_iop(m.iop_dbm)
                    if level != "NORMAL":
                        findings.append(Finding(
                            metric_name="iop",
                            value=m.iop_dbm,
                            unit="dBm",
                            level=level,
                            description=f"入光功率 {m.iop_dbm}dBm → {level}",
                        ))
                        if level == "CRITICAL":
                            status = "CRITICAL"
                        elif status != "CRITICAL":
                            status = "WARNING"

            return AnalysisVerdict(
                status=status if findings else "UNKNOWN",
                findings=findings,
                analysis_mode="rule",
                source_metrics=payload.metrics,
            )

        # Fallback: regex 路径（ReAct 产出的 raw_summary）
        return self._rule_judgment_regex(payload.raw_summary, engine)

    def _rule_judgment_regex(self, raw_summary: str, engine) -> AnalysisVerdict:
        """正则 fallback — 仅用于 ReAct 路径的非结构化输出."""
        findings: list[Finding] = []
        status = "NORMAL"

        spanloss_matches = re.findall(
            r"(?:spanloss|跨段损耗|衰耗)[^\d]*?([\d.]+)\s*dB",
            raw_summary,
            re.IGNORECASE,
        )
        for val_str in spanloss_matches:
            val = float(val_str)
            jr = engine.judge_spanloss(val)
            findings.append(Finding(
                metric_name="spanloss", value=val, unit="dB",
                level=jr.status, description=f"跨段损耗 {val}dB → {jr.status}",
            ))
            if jr.status == "CRITICAL":
                status = "CRITICAL"
            elif jr.status == "WARNING" and status != "CRITICAL":
                status = "WARNING"

        oop_matches = re.findall(
            r"(?:OOP|出光功率)[^\d-]*?(-?[\d.]+)\s*dBm",
            raw_summary,
            re.IGNORECASE,
        )
        for val_str in oop_matches:
            val = float(val_str)
            level = engine.judge_oop(val)
            if level != "NORMAL":
                findings.append(Finding(
                    metric_name="oop", value=val, unit="dBm",
                    level=level, description=f"出光功率 {val}dBm → {level}",
                ))
                if level == "CRITICAL":
                    status = "CRITICAL"
                elif status != "CRITICAL":
                    status = "WARNING"

        return AnalysisVerdict(
            status=status if findings else "UNKNOWN",
            findings=findings,
            analysis_mode="rule",
        )

    async def _llm_analysis(
        self, payload: CollectionPayload, plan: ExecutionPlan, context: dict
    ) -> AgentResult:
        """LLM 深度分析（规则无法覆盖时）."""
        from langchain_core.messages import HumanMessage, SystemMessage

        from ...llm.provider import get_analysis_llm

        try:
            llm = get_analysis_llm()
            system = (
                "你是光纤维护专家。分析数据并给出结论。\n"
                '输出 JSON：{"status": "NORMAL|WARNING|CRITICAL", '
                '"findings": [{"metric_name": "", "value": 0, "unit": "", '
                '"level": "", "description": ""}], "suggestion": "...", '
                '"needs_more_data": false, "additional_query": null}\n'
                "如果数据不足以判断，设 needs_more_data=true 并说明需要什么数据。"
            )
            # 使用结构化数据构建 user message
            data_desc = payload.model_dump_json(exclude_none=True)
            user_msg = (
                f"## 数据\n{data_desc}\n\n"
                f"## 用户问题\n{context.get('user_input', '')}"
            )

            response = await llm.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=user_msg),
                ]
            )

            # 解析为 typed verdict
            content = response.content if hasattr(response, "content") else str(response)
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                raw = json.loads(json_match.group())
                verdict = AnalysisVerdict(
                    status=raw.get("status", "UNKNOWN"),
                    findings=[Finding(**f) for f in raw.get("findings", []) if isinstance(f, dict)],
                    suggestion=raw.get("suggestion", ""),
                    analysis_mode="llm",
                    needs_more_data=raw.get("needs_more_data", False),
                    additional_query=raw.get("additional_query"),
                    source_metrics=payload.metrics,
                )
            else:
                verdict = AnalysisVerdict(
                    status="UNKNOWN",
                    findings=[Finding(description=content[:200])],
                    analysis_mode="llm",
                )

            return AgentResult(
                layer=self.layer,
                success=True,
                data={"verdict": verdict.model_dump(), "analysis_mode": "llm"},
                needs_more_data=verdict.needs_more_data,
                additional_query=verdict.additional_query,
                llm_calls=1,
            )
        except Exception as e:
            logger.error(f"[AnalysisAgent] LLM analysis failed: {e}")
            # 降级：返回有损但可用的结果
            fallback = AnalysisVerdict(
                status="UNKNOWN",
                findings=[Finding(description="分析服务暂时不可用")],
                suggestion="请稍后重试",
                analysis_mode="llm",
            )
            return AgentResult(
                layer=self.layer,
                success=False,
                error=f"LLM 分析失败: {e}",
                data={"verdict": fallback.model_dump(), "analysis_mode": "degraded"},
            )
