"""
服务端独立复核（Server-Side Tool Reviewer）—— 提案者-审核者分离（书籍 Ch4）。

【设计原则】
- 对应 AI Agent 设计原则 Chapter 4 的"提案者-审核者"范式：
  提案者（模型）生成工具调用，审核者（独立复核）对照风险配置确认参数
- 审核者接触的是模型生成时不存在的新信息：风险配置、策略约束、参数一致性
- 审核者不能修改自己的门禁（独立于 confirmation_gate 的 HITL 门禁）

【与 confirmation_gate 的关系】
- confirmation_gate: 前端 HITL（TTL/上限/单次消费），用户确认
- tool_reviewer: 服务端独立复核，模型生成参数 vs 策略约束的一致性检查
- 两者互补：reviewer 先过（服务端），confirm 后过（用户）

【决策语义】
- allow: 通过复核，可执行
- block: 拒绝执行（触发配置为高风险但参数越界）
- review: 需人工复核（参数不在白名单但非明确违规）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..governance.tool_risk import ToolRiskLevel, get_tool_risk_engine

logger = logging.getLogger(__name__)

# 参数类型白名单（param 名 → 允许的类型集合）
_ALLOWED_PARAM_TYPES: dict[str, set[type]] = {
    "int": {int},
    "str": {str},
    "bool": {bool},
    "list": {list},
    "float": {int, float},
    "number": {int, float},
    "id": {int, str},  # ID 类参数允许 int 或数字字符串
    "color": {str},
    "time": {str},
    "any": {int, float, str, bool, list, dict, type(None)},
}

# 高风险参数名 → 允许的取值约束（正则）
_HIGH_RISK_PARAM_CONSTRAINTS: dict[str, str] = {
    "fiber_ids": r"^\d+(,\d+)*$",  # 逗号分隔数字
    "board_ids": r"^\d+(,\d+)*$",
    "port_ids": r"^\d+(,\d+)*$",
    "color": r"^(RED|YELLOW|GREEN)$",
    "scope": r"^(all|partial|specific)$",
}

# 需要独立复核的高风险工具（与 tool_risk HIGH confirm_required 对齐）
_REVIEW_REQUIRED_TOOLS: frozenset[str] = frozenset(
    {
        "pull_call_create",
        "pull_call_cancel",
    }
)

# 参数类型声明（工具名 → param 名 → 类型集合名）
_PARAM_TYPE_SPECS: dict[str, dict[str, str]] = {
    "pull_call_create": {
        "fiber_id": "id",
        "reason": "str",
        "timeout": "float",
        "force": "bool",
    },
    "pull_call_cancel": {
        "ticket_id": "id",
        "reason": "str",
    },
}


@dataclass
class ReviewResult:
    """复核结果."""

    tool_name: str
    decision: str  # allow / block / review
    reason: str = ""
    violations: list[str] = field(default_factory=list)

    @property
    def is_allow(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "decision": self.decision,
            "reason": self.reason,
            "violations": self.violations,
        }


class ToolReviewer:
    """服务端独立复核器（纯代码，零 LLM 依赖）。

    【功能说明】
    - 对高风险写工具的参数做服务端复核
    - 校验参数类型与约束，防止模型生成越界参数
    - 将结果记录到审计日志，供前端/后续链路使用
    """

    def __init__(self) -> None:
        self._risk = get_tool_risk_engine()

    def review(self, tool_name: str, params: dict[str, Any], user_input: str = "") -> ReviewResult:
        """复核一次工具调用。

        【参数说明】
            tool_name: 工具名
            params: 模型生成的参数
            user_input: 用户原始输入（用于一致性辅助判断）

        【返回值】
            ReviewResult：allow / block / review + 违规列表
        """
        violations: list[str] = []

        # 1. 工具是否配置为需复核的高风险操作
        profile = self._risk.get_profile(tool_name)
        risk = profile.risk_level if profile else ToolRiskLevel.LOW
        if tool_name not in _REVIEW_REQUIRED_TOOLS and risk != ToolRiskLevel.HIGH:
            # 非高风险工具：仅做参数类型抽查（低开销）
            type_violations = self._check_param_types(tool_name, params)
            if type_violations:
                return ReviewResult(
                    tool_name=tool_name,
                    decision="block",
                    reason="参数类型违规",
                    violations=type_violations,
                )
            return ReviewResult(tool_name=tool_name, decision="allow", reason="低风险，跳过复核")

        # 2. 参数类型检查
        type_violations = self._check_param_types(tool_name, params)
        violations.extend(type_violations)

        # 3. 高风险参数约束检查
        for name, pattern in _HIGH_RISK_PARAM_CONSTRAINTS.items():
            if name in params and params[name] is not None:
                value = str(params[name])
                if not re.fullmatch(pattern, value):
                    violations.append(f"参数 {name}={value!r} 不符合约束 {pattern!r}")

        # 4. 空参数检查（高风险操作必须有明确目标）
        if risk == ToolRiskLevel.HIGH and not params:
            violations.append("高风险操作缺少目标参数")

        # 5. 用户输入一致性（粗粒度：用户输入与参数目标是否相关）
        if user_input and "ticket_id" in params:
            tid = str(params["ticket_id"])
            if tid not in user_input and tid not in user_input.replace("工单", ""):
                # 允许不一致（可能是系统生成的工单号），仅提示不阻断
                logger.info(f"[ToolReviewer] ticket_id={tid} 未在用户输入中直接出现: " f"user_input={user_input[:50]}")

        if violations:
            return ReviewResult(
                tool_name=tool_name,
                decision="block",
                reason="复核未通过",
                violations=violations,
            )
        return ReviewResult(
            tool_name=tool_name,
            decision="allow",
            reason="参数校验通过，允许执行",
        )

    def _check_param_types(self, tool_name: str, params: dict) -> list[str]:
        """参数类型检查."""
        violations: list[str] = []
        specs = _PARAM_TYPE_SPECS.get(tool_name, {})
        for name, value in params.items():
            type_key = specs.get(name, "any")
            allowed_types = _ALLOWED_PARAM_TYPES.get(type_key, {type(None)})
            # bool 是 int 子类，需先排除
            if isinstance(value, bool) and bool not in allowed_types:
                violations.append(f"参数 {name}={value!r} 类型应为 {type_key}，实际为 bool")
            elif not isinstance(value, tuple(allowed_types)) and value is not None:
                violations.append(f"参数 {name}={value!r} 类型应为 {type_key}")
        return violations


# =============================================================================
# 全局单例
# =============================================================================

_reviewer_instance: Optional[ToolReviewer] = None


def get_tool_reviewer() -> ToolReviewer:
    """获取全局 ToolReviewer 单例."""
    global _reviewer_instance
    if _reviewer_instance is None:
        _reviewer_instance = ToolReviewer()
    return _reviewer_instance
