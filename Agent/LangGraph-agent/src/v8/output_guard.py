"""
输出侧护栏 (OutputGuard) — PII 过滤 + 输出验证 + 完整性检查.

【设计原则】
对应 AI Agent 设计原则 Chapter 1 护栏类型：
  - 输出侧护栏：在响应返回用户前执行 PII 过滤和验证
  - 与输入侧护栏（security.py）对称，形成完整约束闭环

【检测规则】
1. PII 检测：光纤 ID 聚合泄露、工单完整编号、用户个人信息
2. 结构化完整性：确保分析结论字段齐全
3. 品牌一致性：检查输出是否包含非预期信息
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OutputGuardVerdict(BaseModel):
    """输出侧护栏裁决."""

    passed: bool = True
    sanitized_output: str = ""
    warnings: list[str] = Field(default_factory=list)
    blocked_reason: Optional[str] = None

    @property
    def is_clean(self) -> bool:
        return self.passed and not self.warnings


# =============================================================================
# PII 检测模式
# =============================================================================

# 光纤 ID 批量泄露：超过 N 个不同光纤 ID 出现在文本中
_FIBER_ID_PATTERN = re.compile(r"(?:光纤|fiber)\s*(?:ID|id|编号)?\s*[:：]?\s*(\d+)")
_FIBER_LIST_PATTERN = re.compile(r"(\d+(?:[,，、;；\s]+)?){5,}")

# 工单完整编号（格式：GD + 12 位数字）
_TICKET_ID_PATTERN = re.compile(r"GD\d{12}")

# 用户个人信息模式
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ID_CARD_PATTERN = re.compile(r"\d{17}[\dXx]")


def _detect_pii(text: str) -> list[str]:
    """检测文本中的 PII 信息，返回警告列表."""
    warnings = []

    # 1. 光纤 ID 批量泄露
    fiber_ids = _FIBER_ID_PATTERN.findall(text)
    if len(set(fiber_ids)) > 3:
        warnings.append(f"检测到 {len(set(fiber_ids))} 个不同光纤 ID，可能构成信息泄露")

    # 2. 工单完整编号
    tickets = _TICKET_ID_PATTERN.findall(text)
    if tickets:
        warnings.append(f"检测到 {len(tickets)} 个工单编号（已脱敏）")

    # 3. 手机号
    phones = _PHONE_PATTERN.findall(text)
    if phones:
        warnings.append(f"检测到 {len(phones)} 个手机号（已脱敏）")

    # 4. 邮箱
    emails = _EMAIL_PATTERN.findall(text)
    if emails:
        warnings.append(f"检测到 {len(emails)} 个邮箱地址（已脱敏）")

    return warnings


def _sanitize_pii(text: str) -> str:
    """脱敏 PII 信息."""
    # 工单编号脱敏：GD123456789012 → GD****9012
    text = _TICKET_ID_PATTERN.sub(lambda m: m.group(0)[:2] + "****" + m.group(0)[-4:], text)
    # 手机号脱敏：13800138000 → 138****8000
    text = _PHONE_PATTERN.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], text)
    # 邮箱脱敏：test@example.com → t***@example.com
    text = _EMAIL_PATTERN.sub(lambda m: m.group()[0] + "***" + m.group()[m.group().find("@") :], text)
    return text


def _validate_structured_output(data: dict) -> list[str]:
    """验证结构化输出完整性，返回缺失字段列表."""
    issues = []

    if not data:
        issues.append("输出数据为空")
        return issues

    # 检查 verdict 完整性
    verdict = data.get("verdict", data)
    if isinstance(verdict, dict):
        required = ["status", "findings"]
        for field in required:
            if field not in verdict or verdict[field] is None:
                issues.append(f"分析结论缺少必需字段: {field}")

        status = verdict.get("status", "")
        valid_statuses = {"NORMAL", "WARNING", "CRITICAL", "UNKNOWN", "DEGRADED"}
        if status and status not in valid_statuses:
            issues.append(f"分析状态值不在允许范围: {status}")

    # 检查 response 字段
    response = data.get("response", "")
    if not response and isinstance(data.get("verdict"), dict):
        issues.append("缺少用户可读的 response 字段")

    return issues


def run_output_guard(
    output: str,
    data: Optional[dict] = None,
    *,
    enable_pii_check: bool = True,
    enable_structured_check: bool = True,
    enable_sanitization: bool = True,
) -> OutputGuardVerdict:
    """执行输出侧护栏检查.

    Args:
        output: 将要返回给用户的文本输出
        data: 结构化数据（用于完整性验证）
        enable_pii_check: 是否启用 PII 检测
        enable_structured_check: 是否启用结构化验证
        enable_sanitization: 是否启用自动脱敏

    Returns:
        OutputGuardVerdict: 护栏裁决结果
    """
    warnings: list[str] = []
    sanitized = output

    # 1. PII 检测
    if enable_pii_check:
        pii_warnings = _detect_pii(output)
        warnings.extend(pii_warnings)
        if enable_sanitization and pii_warnings:
            sanitized = _sanitize_pii(output)

    # 2. 结构化验证
    if enable_structured_check and data:
        struct_issues = _validate_structured_output(data)
        warnings.extend(struct_issues)

    # 3. 品牌/安全检查：自暴露信息
    exposure_patterns = [
        (r"(?:系统|agent|assistant)\s*(?:提示|说|回复|response)", "AI 自暴露"),
        (r"(?:as an ai|i am an ai|我是一个(?:ai|智能|机器人))", "AI 身份自暴露"),
    ]
    for pattern, label in exposure_patterns:
        if re.search(pattern, output, re.IGNORECASE):
            warnings.append(f"品牌安全：检测到 {label}")

    passed = True
    blocked_reason = None

    # 决策逻辑：
    # - PII 检测到工单/手机号 → 自动脱敏 + 警告（不阻塞）
    # - 结构化字段缺失 → 警告（不阻塞）
    # - AI 身份自暴露 → 阻塞
    for w in warnings:
        if "AI 自暴露" in w or "AI 身份自暴露" in w:
            passed = False
            blocked_reason = w
            break

    if not passed:
        logger.warning(f"[OutputGuard] Blocked: {blocked_reason}")
    elif warnings:
        logger.info(f"[OutputGuard] Passed with {len(warnings)} warnings")

    return OutputGuardVerdict(
        passed=passed,
        sanitized_output=sanitized if passed else "",
        warnings=warnings,
        blocked_reason=blocked_reason,
    )
