"""
Rule Judgment Node — Programmatic threshold-based judgment (zero LLM).

Converts raw collected data into structured judgment conclusions.
LLM does NOT participate in this step — pure domain rules.

Domain thresholds:
- SPANLOSS_THRESHOLD = 5.0 dB (warning)
- SPANLOSS_CRITICAL = 8.0 dB (critical)
- OOP_RANGE = (-8.0, -2.0) dBm
- IOP_RANGE = (-15.0, -8.0) dBm
"""

from __future__ import annotations

import logging
import re

from ..config import OOP_RANGE, IOP_RANGE, SPANLOSS_CRITICAL, SPANLOSS_THRESHOLD
from ..governance.threshold_engine import get_threshold_engine
from ..graph.state import MainGraphState, RuleJudgment

logger = logging.getLogger(__name__)


async def rule_judgment_node(state: MainGraphState) -> dict:
    """
    Programmatic judgment: generate structured conclusions from data.

    Delegates to JudgmentEngine (Skill system) with legacy fallback.
    LLM does NOT participate in this step — pure domain rules.
    """
    data_summary = state.get("collected_data_summary", "") or ""

    # 优先使用 Skill 系统的 JudgmentEngine
    try:
        from ..skills.loader import get_registries

        engine = get_registries()["judgment"].engine
        result = engine.evaluate(data_summary)
        if result["findings"]:  # 有匹配结果
            judgment = RuleJudgment(
                status=result["status"],
                findings=result["findings"],
                metrics=result["metrics"],
                suggested_actions=result["actions"],
            )
            logger.info(f"[RuleJudgment] (skill) status={result['status']}, findings={len(result['findings'])}")
            return {"rule_judgment": judgment.model_dump()}
    except (ImportError, KeyError):
        pass  # Fallback

    # Fallback: 原有 if-else 逻辑（渐进迁移期保留）
    return await _legacy_judgment(data_summary)


async def _legacy_judgment(data_summary: str) -> dict:
    """原有硬编码判断逻辑（迁移完成后删除）。"""
    findings: list[str] = []
    metrics: dict = {}
    status = "NORMAL"

    for line in data_summary.split("\n"):
        line_lower = line.lower()

        # Spanloss analysis — 使用 ThresholdEngine 查表
        if "spanloss" in line_lower:
            m = re.search(r"spanloss[=:]\s*([\d.]+)", line, re.IGNORECASE)
            if m:
                spanloss = float(m.group(1))
                metrics["spanloss"] = spanloss
                engine = get_threshold_engine()
                jr = engine.judge_spanloss(spanloss)
                metrics["threshold_source"] = jr.threshold_warning
                if jr.status == "CRITICAL":
                    findings.append(
                        f"衰耗 {spanloss}dB 严重超标（阈值 {jr.threshold_warning}dB，"
                        f"超出 {jr.percent_over:.0f}%）"
                    )
                    status = "CRITICAL"
                elif jr.status == "WARNING":
                    findings.append(
                        f"衰耗 {spanloss}dB 超过阈值 {jr.threshold_warning}dB"
                        f"（超出 {jr.percent_over:.0f}%）"
                    )
                    if status != "CRITICAL":
                        status = "WARNING"
                else:
                    findings.append(f"衰耗 {spanloss}dB，在阈值 {jr.threshold_warning}dB 内，正常")

        # OOP (Output Optical Power) analysis — 使用 ThresholdEngine
        if "oop" in line_lower or "输出光功率" in line:
            m = re.search(r"(?:oop|输出光功率)[=:]\s*(-?[\d.]+)", line, re.IGNORECASE)
            if m:
                oop = float(m.group(1))
                metrics["oop"] = oop
                engine = get_threshold_engine()
                if engine.judge_oop(oop) != "NORMAL":
                    findings.append(f"输出光功率 {oop}dBm 超出正常范围 {engine.oop_range}")
                    if status != "CRITICAL":
                        status = "WARNING"

        # IOP (Input Optical Power) analysis — 使用 ThresholdEngine
        if "iop" in line_lower or "输入光功率" in line:
            m = re.search(r"(?:iop|输入光功率)[=:]\s*(-?[\d.]+)", line, re.IGNORECASE)
            if m:
                iop = float(m.group(1))
                metrics["iop"] = iop
                engine = get_threshold_engine()
                if engine.judge_iop(iop) != "NORMAL":
                    findings.append(f"输入光功率 {iop}dBm 超出正常范围 {engine.iop_range}")
                    if status != "CRITICAL":
                        status = "WARNING"

        # Alarm analysis
        if "告警" in line or "alarm" in line_lower:
            m = re.search(r"CRITICAL[=:]\s*(\d+)", line, re.IGNORECASE)
            if m and int(m.group(1)) > 0:
                findings.append(f"存在 {m.group(1)} 条 CRITICAL 告警")
                status = "CRITICAL"
            m = re.search(r"MAJOR[=:]\s*(\d+)", line, re.IGNORECASE)
            if m and int(m.group(1)) > 0:
                findings.append(f"存在 {m.group(1)} 条 MAJOR 告警")
                if status != "CRITICAL":
                    status = "WARNING"

        # Color analysis
        if "color" in line_lower or "颜色" in line:
            if "RED" in line.upper() or "红色" in line:
                metrics["color"] = "RED"
                if status == "NORMAL":
                    findings.append("光纤颜色为红色（异常）")
                    status = "WARNING"
            elif "YELLOW" in line.upper() or "黄色" in line:
                metrics["color"] = "YELLOW"

    # Generate suggested actions based on status
    suggested_actions: list[str] = []
    if status == "CRITICAL":
        suggested_actions.append("立即派单检修")
        suggested_actions.append("检查关联光纤是否受影响")
        suggested_actions.append("通知值班主管")
    elif status == "WARNING":
        suggested_actions.append("列入下次巡检计划")
        suggested_actions.append("持续监控趋势变化")

    # If no findings, add default
    if not findings:
        findings.append("未发现明显异常")

    judgment = RuleJudgment(
        status=status,
        findings=findings,
        metrics=metrics,
        suggested_actions=suggested_actions,
    )

    logger.info(f"[RuleJudgment] status={status}, findings={len(findings)}")

    return {"rule_judgment": judgment.model_dump()}
