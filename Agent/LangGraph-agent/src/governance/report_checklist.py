"""
报告确定性清单（Report Checklist）—— 评估器的硬门（书籍 Ch6：确定性检查先行）。

【设计原则】
- 可形式化的质量维度全部由代码校验，LLM 不再是唯一裁判
  （书籍 Ch10：同模型自我审查无效，确定性 veto 优先）
- 任一清单项失败 → 报告直接判不通过，feedback 附具体失败项与证据，
  供 report_generator 定向修正
- 数字校验复用 number_validator 的提取逻辑

【清单项】
1. numbers_grounded: 报告中的数字必须能溯源到源数据（幻觉 veto）
2. sections_present: 报告章节齐全（按报告类型）
3. severity_consistent: 结论严重级别与程序化规则判断一致
"""

from __future__ import annotations

import re
from typing import Any

from .number_validator import extract_numbers

# 日期/标识符防护：2026-08-14 中的 -08/-14 会被数字正则误提为负数，
# 先行把数字之间的连字符替换为空格（日期、fiber-5 等 ID 写法），
# 保留真正的负数（如 -8.5dBm，前面无数字）
_DATELIKE_PATTERN = re.compile(r"(?<=\d)-(?=\d)")

# 良性数字：序号/日期时间/百分比等无溯源要求的常见数字
# （报告含生成时间 2026-08-14 等，年月日时分秒不要求出现在源数据中）
_BENIGN_NUMBERS: set[float] = (
    {float(i) for i in range(0, 32)}
    | {float(i) for i in range(2020, 2041)}
    | {0.0, 1.0, 2.0, 3.0, 5.0, 10.0, 60.0, 100.0}
)

# 各报告类型的必备章节关键词（匹配标题行，宽松匹配关键词子串）
_REQUIRED_SECTIONS = {
    "fault": ["基本信息", "故障", "影响", "根因", "处理"],
    "daily": ["基本信息", "统计", "异常", "分析", "建议"],
    "generic": ["概要", "发现"],
}


def _allowed_numbers(source_texts: list[str]) -> set[float]:
    """从所有源文本中提取允许出现的数字集合。"""
    allowed: set[float] = set(_BENIGN_NUMBERS)
    for text in source_texts:
        if text:
            allowed.update(float(n) for n in extract_numbers(str(text)))
    return allowed


def _headings(report: str) -> list[str]:
    return [line.strip().lstrip("#").strip() for line in report.splitlines() if line.strip().startswith("#")]


def _report_numbers(report: str) -> set[float]:
    """提取报告数字（先剥离日期/ID 连字符，避免 -08 类误提）。"""
    return {float(n) for n in extract_numbers(_DATELIKE_PATTERN.sub(" ", report))}


def check_numbers_grounded(report: str, source_texts: list[str]) -> dict:
    """校验报告数字全部可溯源到源数据。"""
    allowed = _allowed_numbers(source_texts)
    report_nums = _report_numbers(report)
    hallucinated = sorted(report_nums - allowed)
    if not hallucinated:
        return {"check": "numbers_grounded", "passed": True, "evidence": "所有数字均可溯源"}
    sample = ", ".join(str(n) for n in hallucinated[:5])
    more = f" 等 {len(hallucinated)} 个" if len(hallucinated) > 5 else ""
    return {
        "check": "numbers_grounded",
        "passed": False,
        "evidence": f"幻觉数字: {sample}{more}（不在源数据中，必须删除或替换为源数据数值）",
    }


def check_sections_present(report: str) -> dict:
    """校验报告章节齐全（按标题识别报告类型）。"""
    headings_text = " ".join(_headings(report))
    if "日报" in report[:60]:
        report_type, required = "daily", _REQUIRED_SECTIONS["daily"]
    elif "故障" in report[:60] or "分析" in report[:60]:
        report_type, required = "fault", _REQUIRED_SECTIONS["fault"]
    else:
        report_type, required = "generic", _REQUIRED_SECTIONS["generic"]

    missing = [kw for kw in required if kw not in headings_text]
    if not missing:
        return {"check": "sections_present", "passed": True, "evidence": f"{report_type} 章节齐全"}
    return {
        "check": "sections_present",
        "passed": False,
        "evidence": f"{report_type} 报告缺失章节关键词: {', '.join(missing)}",
    }


def check_severity_consistent(rule_judgment: dict[str, Any], analysis_verdict: dict[str, Any]) -> dict:
    """校验分析结论严重级别与程序化规则判断一致。"""
    judgment_status = (rule_judgment or {}).get("status")
    verdict_severity = (analysis_verdict or {}).get("severity")
    if not judgment_status or not verdict_severity:
        return {"check": "severity_consistent", "passed": True, "evidence": "无对比对象，跳过"}
    if judgment_status == verdict_severity:
        return {
            "check": "severity_consistent",
            "passed": True,
            "evidence": f"一致: {judgment_status}",
        }
    return {
        "check": "severity_consistent",
        "passed": False,
        "evidence": (
            f"规则判断为 {judgment_status}（程序化，可信），"
            f"但分析结论为 {verdict_severity}，报告结论须与规则判断一致"
        ),
    }


def run_report_checklist(
    report: str,
    collected_data_summary: str,
    rule_judgment: dict[str, Any],
    analysis_verdict: dict[str, Any] | None = None,
) -> list[dict]:
    """执行完整确定性清单，返回各检查项结果列表。

    【参数说明】
        report: 待评估的报告文本
        collected_data_summary: 数据收集摘要（数字溯源的源数据）
        rule_judgment: 程序化规则判断（severity 一致性的可信基准）
        analysis_verdict: LLM 分析结论（severity 对比对象，可缺省）
    """
    judgment_str = str(rule_judgment) if rule_judgment else ""
    source_texts = [collected_data_summary or "", judgment_str]
    return [
        check_numbers_grounded(report, source_texts),
        check_sections_present(report),
        check_severity_consistent(rule_judgment or {}, analysis_verdict or {}),
    ]
