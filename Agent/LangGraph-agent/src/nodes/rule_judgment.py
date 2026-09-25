"""
规则判断节点 —— 基于阈值的程序化判断（零 LLM 调用）。

【功能说明】
将收集到的原始数据转换为结构化的判断结论。
LLM 不参与此步骤 —— 纯领域规则判断。

【领域阈值】
- SPANLOSS_THRESHOLD = 5.0 dB（告警）
- SPANLOSS_CRITICAL = 8.0 dB（严重）
- OOP_RANGE = (-8.0, -2.0) dBm（输出光功率正常范围）
- IOP_RANGE = (-15.0, -8.0) dBm（输入光功率正常范围）

【面试知识点】
  Q: 为什么判断步骤不用 LLM？
  A: 阈值判断是确定性的，LLM 反而可能引入幻觉（如把 3.2dB 说成“约 3dB”）。
     程序化判断保证数值精确性，是叙述员（Narrator）的可靠输入源。
"""

from __future__ import annotations

import logging
import re

from ..governance.threshold_engine import get_threshold_engine
from ..graph.state import MainGraphState, RuleJudgment

logger = logging.getLogger(__name__)


async def rule_judgment_node(state: MainGraphState) -> dict:
    """程序化判断节点：从数据生成结构化结论。

    【功能说明】
    优先使用 Skill 系统的 JudgmentEngine（可配置化），
    未可用时 fallback 到原有硬编码逻辑。

    【输入】state.collected_data_summary（数据收集子图的输出摘要）
    【输出】rule_judgment（RuleJudgment 序列化，含 status/findings/metrics）
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
        pass  # 兜底

    # Fallback: 原有 if-else 逻辑（渐进迁移期保留）
    return await _legacy_judgment(data_summary)


async def _legacy_judgment(data_summary: str) -> dict:
    """原有硬编码判断逻辑（迁移完成后删除）。

    【功能说明】
    逐行扫描数据摘要，提取关键指标并与阈值对比：
    - 跨段衰耗（spanloss）→ 查表 ThresholdEngine
    - 输出光功率（OOP）→ 范围检查
    - 输入光功率（IOP）→ 范围检查
    - 告警信息 → 严重程度统计
    - 颜色状态 → RED/YELLOW 识别

    【兼容性说明】
    数据摘要由 LLM 数据收集器生成，格式不固定，可能是：
    - JSON: {"spanloss": 9.77} 或 {"衰耗": 9.77}
    - 文本: spanloss=9.77 或 衰耗: 9.77dB
    - 告警: [{"alarm_level": "CRITICAL"}] 或 CRITICAL=1
    正则需覆盖所有常见格式。
    """
    findings: list[str] = []
    metrics: dict = {}
    status = "NORMAL"

    # === 第一遍：从原始文本中提取所有指标 ===

    # Spanloss：兼容 JSON key "spanloss"/"衰耗" 和文本 "spanloss="/"衰耗="
    spanloss_patterns = [
        r'"spanloss"\s*:\s*(-?[\d.]+)',  # JSON: "spanloss": 9.77 或 -2.75
        r'"衰耗"\s*:\s*(-?[\d.]+)',  # JSON: "衰耗": 9.77
        r"spanloss[=:]\s*(-?[\d.]+)",  # 文本: spanloss=9.77 或 spanloss: -2.75
        r"衰耗[=:为]?\s*(-?[\d.]+)\s*dB",  # 文本: 衰耗=9.77dB / 衰耗为 -2.75dB
        r"跨段衰耗[=:为]?\s*(-?[\d.]+)",  # 文本: 跨段衰耗: 9.77
    ]
    for pattern in spanloss_patterns:
        m = re.search(pattern, data_summary, re.IGNORECASE)
        if m:
            spanloss = float(m.group(1))
            metrics["spanloss"] = spanloss
            engine = get_threshold_engine()
            jr = engine.judge_spanloss(spanloss)
            metrics["threshold_source"] = jr.threshold_warning
            if jr.status == "CRITICAL":
                findings.append(
                    f"衰耗 {spanloss}dB 严重超标（阈值 {jr.threshold_warning}dB，" f"超出 {jr.percent_over:.0f}%）"
                )
                status = "CRITICAL"
            elif jr.status == "WARNING":
                findings.append(
                    f"衰耗 {spanloss}dB 超过阈值 {jr.threshold_warning}dB" f"（超出 {jr.percent_over:.0f}%）"
                )
                if status != "CRITICAL":
                    status = "WARNING"
            else:
                findings.append(f"衰耗 {spanloss}dB，在阈值 {jr.threshold_warning}dB 内，正常")
            break

    # OOP（输出光功率）
    oop_patterns = [
        r'"src_oop"\s*:\s*(-?[\d.]+)',  # JSON: "src_oop": -19.5
        r'"oop"\s*:\s*(-?[\d.]+)',  # JSON: "oop": -19.5
        r"(?:oop|输出光功率)[=:]\s*(-?[\d.]+)",  # 文本: oop=-19.5 / 输出光功率=-19.5
    ]
    for pattern in oop_patterns:
        m = re.search(pattern, data_summary, re.IGNORECASE)
        if m:
            oop = float(m.group(1))
            metrics["oop"] = oop
            engine = get_threshold_engine()
            if engine.judge_oop(oop) != "NORMAL":
                findings.append(f"输出光功率 {oop}dBm 超出正常范围 {engine.oop_range}")
                if status != "CRITICAL":
                    status = "WARNING"
            break

    # IOP（输入光功率）
    iop_patterns = [
        r'"dst_iop"\s*:\s*(-?[\d.]+)',  # JSON: "dst_iop": -29.3
        r'"iop"\s*:\s*(-?[\d.]+)',  # JSON: "iop": -29.3
        r"(?:iop|输入光功率)[=:]\s*(-?[\d.]+)",  # 文本: iop=-29.3 / 输入光功率=-29.3
    ]
    for pattern in iop_patterns:
        m = re.search(pattern, data_summary, re.IGNORECASE)
        if m:
            iop = float(m.group(1))
            metrics["iop"] = iop
            engine = get_threshold_engine()
            if engine.judge_iop(iop) != "NORMAL":
                findings.append(f"输入光功率 {iop}dBm 超出正常范围 {engine.iop_range}")
                if status != "CRITICAL":
                    status = "WARNING"
            break

    # 告警分析 —— 兼容多种格式
    # 格式1: JSON 数组 [{"alarm_level": "CRITICAL"}, ...]
    critical_count = len(re.findall(r'"alarm_level"\s*:\s*"CRITICAL"', data_summary))
    major_count = len(re.findall(r'"alarm_level"\s*:\s*"MAJOR"', data_summary))
    minor_count = len(re.findall(r'"alarm_level"\s*:\s*"MINOR"', data_summary))

    # 格式2: 文本 CRITICAL=N / CRITICAL: N
    if critical_count == 0:
        m = re.search(r"CRITICAL[=:]\s*(\d+)", data_summary, re.IGNORECASE)
        if m:
            critical_count = int(m.group(1))
    if major_count == 0:
        m = re.search(r"MAJOR[=:]\s*(\d+)", data_summary, re.IGNORECASE)
        if m:
            major_count = int(m.group(1))

    # 格式3: "[CRITICAL]" 或 "严重" 关键词
    if critical_count == 0:
        critical_count = len(re.findall(r"\[CRITICAL\]|严重告警", data_summary))
    if major_count == 0:
        major_count = len(re.findall(r"\[MAJOR\]|主要告警", data_summary))

    # 记录告警指标
    if critical_count > 0:
        metrics["alarm_critical"] = critical_count
    if major_count > 0:
        metrics["alarm_major"] = major_count
    if minor_count > 0:
        metrics["alarm_minor"] = minor_count

    # 生成告警发现
    if critical_count > 0:
        findings.append(f"存在 {critical_count} 条 CRITICAL（严重）告警")
        status = "CRITICAL"
    if major_count > 0:
        findings.append(f"存在 {major_count} 条 MAJOR（主要）告警")
        if status != "CRITICAL":
            status = "WARNING"
    if minor_count > 0:
        findings.append(f"存在 {minor_count} 条 MINOR（次要）告警")

    # 颜色分析
    if "color" in data_summary.lower() or "颜色" in data_summary:
        if "RED" in data_summary.upper() or "红色" in data_summary:
            metrics["color"] = "RED"
            if status == "NORMAL":
                findings.append("光纤颜色为红色（异常）")
                status = "WARNING"
        elif "YELLOW" in data_summary.upper() or "黄色" in data_summary:
            metrics["color"] = "YELLOW"

    # 根据状态生成建议措施
    suggested_actions: list[str] = []
    if status == "CRITICAL":
        suggested_actions.append("立即派单检修")
        suggested_actions.append("检查关联光纤是否受影响")
        suggested_actions.append("通知值班主管")
    elif status == "WARNING":
        suggested_actions.append("列入下次巡检计划")
        suggested_actions.append("持续监控趋势变化")

    # 若无发现，则添加默认项
    if not findings:
        findings.append("未发现明显异常")

    judgment = RuleJudgment(
        status=status,
        findings=findings,
        metrics=metrics,
        suggested_actions=suggested_actions,
    )

    logger.info(f"[RuleJudgment] status={status}, findings={len(findings)}, metrics={list(metrics.keys())}")

    return {"rule_judgment": judgment.model_dump()}
