"""
v8 安全层 — InputGuard + 参数校验 + Clarification.

职责：
1. Prompt 注入检测（复用 v7.1 正则规则）
2. 输入长度截断
3. 参数完整性校验（缺 fiber_id → 追问）
4. 生成 clarification 信号（Orchestrator 识别后跳过 Collection）

零 LLM 调用，纯规则，延迟 < 1ms。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# =============================================================================
# Prompt 注入检测（复用 v7.1 规则）
# =============================================================================

INJECTION_PATTERNS = [
    r"忽略(以上|之前|所有)(指令|提示|规则|设定)",
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
    r"你(现在|从现在起)是(?!.*光纤)",
    r"act\s+as\s+(if|though)",
    r"pretend\s+(you|to\s+be)",
    r"(system|系统)\s*prompt",
    r"删除(所有|全部|一切)(光纤|数据|记录|配置)",
    r"DROP\s+TABLE",
    r"<script",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

MAX_INPUT_LENGTH = 2000

# 需要 fiber_id 的场景（参数校验用）
_SCENARIOS_REQUIRING_FIBER_ID = {
    "spanloss_check",
    "oop_check",
    "iop_check",
    "performance_query",
    "fiber_status",
    "alarm_check",
}


# =============================================================================
# 安全检查结果
# =============================================================================


class SecurityVerdict(BaseModel):
    """安全层检查结果."""

    passed: bool = True
    blocked_reason: str = ""
    sanitized_input: str = ""
    needs_clarification: bool = False
    clarification_question: str = ""
    missing_params: list[str] = Field(default_factory=list)


# =============================================================================
# 核心检查逻辑
# =============================================================================


def check_injection(user_input: str) -> Optional[str]:
    """检测 prompt 注入. 返回 None 表示安全，否则返回拦截原因."""
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(user_input):
            return f"检测到注入模式: {pattern.pattern}"
    return None


def sanitize_input(user_input: str) -> str:
    """输入清洗：长度截断."""
    if len(user_input) > MAX_INPUT_LENGTH:
        logger.info(f"[Security] Input truncated to {MAX_INPUT_LENGTH} chars")
        return user_input[:MAX_INPUT_LENGTH]
    return user_input


def validate_params(
    intent: str, params: dict[str, Any]
) -> Optional[str]:
    """
    参数完整性校验.

    返回 None 表示参数完整，否则返回追问文本。
    """
    if intent in _SCENARIOS_REQUIRING_FIBER_ID:
        fiber_ids = params.get("fiber_ids", [])
        if not fiber_ids:
            return "请提供要查询的光纤 ID（例如：查看光纤1的状态）"
    return None


def run_security_check(
    user_input: str,
    intent: str = "",
    params: Optional[dict[str, Any]] = None,
) -> SecurityVerdict:
    """
    完整安全检查流水线.

    顺序：注入检测 → 长度截断 → 参数校验
    """
    # Step 1: 注入检测
    injection = check_injection(user_input)
    if injection:
        logger.warning(f"[Security] Blocked: {injection}")
        return SecurityVerdict(
            passed=False,
            blocked_reason=injection,
            sanitized_input="",
        )

    # Step 2: 长度截断
    sanitized = sanitize_input(user_input)

    # Step 3: 参数校验（仅在 intent 已知时）
    if intent and params is not None:
        clarification = validate_params(intent, params)
        if clarification:
            return SecurityVerdict(
                passed=True,
                sanitized_input=sanitized,
                needs_clarification=True,
                clarification_question=clarification,
                missing_params=["fiber_ids"],
            )

    return SecurityVerdict(passed=True, sanitized_input=sanitized)
