"""
叙述校验节点 [v7.1] —— 程序化输出验证（零 LLM 调用）。

【功能说明】
确保 LLM 叙述员没有篡改规则判断中的数据。

【设计动机】
即使提示词中写了“不要修改数值”，LLM 仍有约 1% 的概率
将 3.2dB 写成“约 3dB”或省略关键指标。在电信安全等级 3
场景中，这 1% 是不可接受的。叙述校验器程序化地关闭这个缺口。

【验证规则】
① 关键数值必须在叙述中原样出现
② 颜色词必须精确匹配
③ 不得出现判断中不存在的告警类型（防幻觉）
④ 严重程度词一致性（CRITICAL 不能说“正常”）

验证失败 → 路由到 template_fallback（不是 LLM 重试）

【面试知识点】
  Q: 为什么验证失败不重试 LLM 而是用模板？
  A: ① 重试可能再次失败，浪费 token；② 模板输出保证数据准确性，
     虽然可读性稍差但不会误导运维人员。在电信场景中，准确性 > 可读性。
"""

from __future__ import annotations

import logging

from ..graph.state import MainGraphState

logger = logging.getLogger(__name__)

# 颜色映射表（用于验证叙述员输出中的颜色表述）
COLOR_MAP = {
    "GREEN": "绿色",
    "YELLOW": "黄色",
    "RED": "红色",
    "1": "绿色",
    "2": "黄色",
    "3": "红色",
}

# 已知告警类型列表（用于幻觉检测：叙述员不得编造不存在的告警类型）
ALARM_TYPES = ["LOS", "LOF", "AIS", "RDI", "B1_EXC", "B2_EXC"]


async def narrator_validator_node(state: MainGraphState) -> dict:
    """叙述员输出程序化验证节点（零 LLM，< 1ms）。

    【功能说明】
    将叙述员的自然语言输出与 RuleJudgment 的结构化数据进行对比，
    检查数值、颜色、告警类型、严重程度是否一致。

    【输入】state.rule_judgment, state.narration
    【输出】narrator_validation_passed（True/False）
    """
    judgment = state.get("rule_judgment")
    narration = state.get("narration", "")

    # 若无判断或叙述内容，则跳过校验
    if not judgment or not narration:
        return {"narrator_validation_passed": True}

    errors: list[str] = []
    metrics = judgment.get("metrics", {})
    findings = judgment.get("findings", [])
    status = judgment.get("status", "NORMAL")

    # 规则 ①：关键数值必须在叙述中原样出现
    for key in ["spanloss", "oop", "iop", "fiber_id"]:
        val = metrics.get(key)
        if val is not None and str(val) not in narration:
            errors.append(f"数值 {val} ({key}) 在表述中缺失")

    # 规则 ②：颜色词必须精确匹配
    color_val = metrics.get("color")
    if color_val:
        expected_cn = COLOR_MAP.get(str(color_val))
        if expected_cn and expected_cn not in narration:
            errors.append(f"颜色表述不匹配：期望 {expected_cn}")

    # 规则 ③：不得出现幻觉告警类型
    alarm_types_in_judgment = set()
    for f in findings:
        for at in ALARM_TYPES:
            if at in f:
                alarm_types_in_judgment.add(at)

    for at in ALARM_TYPES:
        if at in narration and at not in alarm_types_in_judgment:
            errors.append(f"幻觉告警类型：{at}")

    # 规则 ④：严重程度词一致性检查
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
