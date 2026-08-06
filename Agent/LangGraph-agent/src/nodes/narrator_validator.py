"""
Narrator Validator Node [v7.1] — Programmatic output validation (zero LLM).

Ensures LLM narration hasn't tampered with rule judgment data.

Design motivation:
  Even with "do not modify values" in the prompt, LLM has ~1% chance
  of writing 3.2dB as "约3dB" or omitting key metrics. In telecom
  security level 3 scenarios, this 1% is unacceptable.
  NarratorValidator closes this gap programmatically.

Validation rules:
  ① Key numeric values must appear verbatim in narration
  ② Color words must match exactly
  ③ No alarm types absent from judgment (anti-hallucination)
  ④ Severity word consistency (CRITICAL cannot say "正常")

Validation failure → route to template_fallback (not LLM retry).
"""

from __future__ import annotations

import logging

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)

# Color mapping for validation
COLOR_MAP = {
    "GREEN": "绿色", "YELLOW": "黄色", "RED": "红色",
    "1": "绿色", "2": "黄色", "3": "红色",
}

# Known alarm types for hallucination detection
ALARM_TYPES = ["LOS", "LOF", "AIS", "RDI", "B1_EXC", "B2_EXC"]


async def narrator_validator_node(state: MainGraphState) -> dict:
    """
    Narrator output programmatic validation (zero LLM, < 1ms).

    Checks narration against rule_judgment for data integrity.
    """
    judgment = state.get("rule_judgment")
    narration = state.get("narration", "")

    # Skip validation if no judgment or narration
    if not judgment or not narration:
        return {"narrator_validation_passed": True}

    errors: list[str] = []
    metrics = judgment.get("metrics", {})
    findings = judgment.get("findings", [])
    status = judgment.get("status", "NORMAL")

    # Rule ①: Key numeric values must appear verbatim
    for key in ["spanloss", "oop", "iop", "fiber_id"]:
        val = metrics.get(key)
        if val is not None and str(val) not in narration:
            errors.append(f"数值 {val} ({key}) 在表述中缺失")

    # Rule ②: Color words must match exactly
    color_val = metrics.get("color")
    if color_val:
        expected_cn = COLOR_MAP.get(str(color_val))
        if expected_cn and expected_cn not in narration:
            errors.append(f"颜色表述不匹配：期望 {expected_cn}")

    # Rule ③: No hallucinated alarm types
    alarm_types_in_judgment = set()
    for f in findings:
        for at in ALARM_TYPES:
            if at in f:
                alarm_types_in_judgment.add(at)

    for at in ALARM_TYPES:
        if at in narration and at not in alarm_types_in_judgment:
            errors.append(f"幻觉告警类型：{at}")

    # Rule ④: Severity word consistency
    if status == "CRITICAL" and "正常" in narration and "不正常" not in narration:
        errors.append("严重程度表述矛盾：判断为 CRITICAL 但表述含'正常'")
    if status == "NORMAL" and ("严重" in narration or "超标" in narration):
        errors.append("严重程度表述矛盾：判断为 NORMAL 但表述含严重/超标")

    if errors:
        logger.warning(f"[NarratorValidator] Validation failed: {errors}")
        return {
            "narrator_validation_passed": False,
            "audit_trail": [{"event": "narrator_validation_failed", "errors": errors}],
        }

    return {"narrator_validation_passed": True}
