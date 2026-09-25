"""
工具风险评级系统 (ToolRiskRating).

【设计原则】
对应 AI Agent 设计原则 Chapter 1 执行侧护栏：
  - 为每个工具标注风险等级（低/中/高）
  - 高风险操作触发额外确认门禁
  - 支持动态风险评估（参数组合可能升级风险）

【风险等级】
  LOW    — 只读查询，无副作用，无数据泄露风险
  MEDIUM — 读取+有限写入，批量操作，数据导出
  HIGH   — 写入/删除/不可逆操作，工单创建取消
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolRiskProfile(BaseModel):
    """工具风险配置."""

    tool_name: str
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    dynamic_risk: bool = False
    confirm_required: bool = False
    audit_required: bool = True
    description: str = ""


class DynamicRiskRule(BaseModel):
    """动态风险评估规则."""

    tool_name: str
    condition: str  # Python 表达式
    upgrade_to: ToolRiskLevel


# =============================================================================
# 工具风险默认注册表
# =============================================================================

_DEFAULT_RISK_PROFILES: dict[str, ToolRiskProfile] = {
    # ── 只读查询工具 (LOW) ──
    "fiber_spanloss_query": ToolRiskProfile(
        tool_name="fiber_spanloss_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询光纤跨段衰耗，只读无副作用",
    ),
    "fiber_performance_query": ToolRiskProfile(
        tool_name="fiber_performance_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询光纤 OOP/IOP 性能，只读",
    ),
    "fiber_connection_query": ToolRiskProfile(
        tool_name="fiber_connection_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询光纤连接关系，只读",
    ),
    "fiber_alarm_query": ToolRiskProfile(
        tool_name="fiber_alarm_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询光纤告警，只读",
    ),
    "fiber_route_query": ToolRiskProfile(
        tool_name="fiber_route_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询光纤路由，只读",
    ),
    "ne_query": ToolRiskProfile(
        tool_name="ne_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询网元设备信息，只读",
    ),
    "alarm_query": ToolRiskProfile(
        tool_name="alarm_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询告警历史，只读",
    ),
    "topology_query": ToolRiskProfile(
        tool_name="topology_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询网络拓扑，只读",
    ),
    "knowledge_query": ToolRiskProfile(
        tool_name="knowledge_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询知识库，只读",
    ),
    # ── 批量查询 (MEDIUM) ──
    "batch_spanloss_query": ToolRiskProfile(
        tool_name="batch_spanloss_query",
        risk_level=ToolRiskLevel.MEDIUM,
        dynamic_risk=True,
        description="批量查询跨段衰耗，大量光纤时升级为 HIGH",
    ),
    "batch_performance_query": ToolRiskProfile(
        tool_name="batch_performance_query",
        risk_level=ToolRiskLevel.MEDIUM,
        dynamic_risk=True,
        description="批量查询性能，大量光纤时升级为 HIGH",
    ),
    # ── 导出工具 (MEDIUM) ──
    "export_spanloss_report": ToolRiskProfile(
        tool_name="export_spanloss_report",
        risk_level=ToolRiskLevel.MEDIUM,
        dynamic_risk=True,
        description="导出衰耗报告，大范围导出时升级为 HIGH",
    ),
    "export_performance_report": ToolRiskProfile(
        tool_name="export_performance_report",
        risk_level=ToolRiskLevel.MEDIUM,
        dynamic_risk=True,
        description="导出性能报告",
    ),
    "export_alarm_report": ToolRiskProfile(
        tool_name="export_alarm_report",
        risk_level=ToolRiskLevel.MEDIUM,
        description="导出告警报告",
    ),
    # ── 工单操作 (HIGH) ──
    "pull_call_create": ToolRiskProfile(
        tool_name="pull_call_create",
        risk_level=ToolRiskLevel.HIGH,
        confirm_required=True,
        description="创建工单，不可逆操作，需用户确认",
    ),
    "pull_call_cancel": ToolRiskProfile(
        tool_name="pull_call_cancel",
        risk_level=ToolRiskLevel.HIGH,
        confirm_required=True,
        description="取消工单，不可逆操作，需用户确认",
    ),
    "pull_call_query": ToolRiskProfile(
        tool_name="pull_call_query",
        risk_level=ToolRiskLevel.LOW,
        description="查询工单状态，只读",
    ),
    # ── 内部工具 (MEDIUM) ──
    "memory_save": ToolRiskProfile(
        tool_name="memory_save",
        risk_level=ToolRiskLevel.MEDIUM,
        description="写入经验记忆，可能影响后续判断",
    ),
    "report_format": ToolRiskProfile(
        tool_name="report_format",
        risk_level=ToolRiskLevel.LOW,
        description="格式化报告，只读转换",
    ),
    "fallback_response": ToolRiskProfile(
        tool_name="fallback_response",
        risk_level=ToolRiskLevel.LOW,
        description="降级响应，无外部影响",
    ),
}


class ToolRiskEngine:
    """工具风险评级引擎."""

    def __init__(self):
        self._profiles: dict[str, ToolRiskProfile] = dict(_DEFAULT_RISK_PROFILES)
        self._dynamic_rules: list[DynamicRiskRule] = []

    def get_profile(self, tool_name: str) -> ToolRiskProfile:
        """获取工具风险配置."""
        return self._profiles.get(
            tool_name,
            ToolRiskProfile(
                tool_name=tool_name,
                risk_level=ToolRiskLevel.LOW,
                description="未注册工具，默认低风险",
            ),
        )

    def evaluate_risk(self, tool_name: str, params: Optional[dict] = None) -> ToolRiskLevel:
        """评估工具调用的实际风险（含动态评估）."""
        profile = self.get_profile(tool_name)
        level = profile.risk_level

        # 动态风险评估
        if profile.dynamic_risk and params:
            for rule in self._dynamic_rules:
                if rule.tool_name == tool_name:
                    try:
                        condition = rule.condition
                        if "fiber_count" in condition:
                            fiber_ids = params.get("fiber_ids", [])
                            fiber_count = len(fiber_ids) if fiber_ids else 1
                            if fiber_count > 20:
                                level = max(level, rule.upgrade_to, key=lambda x: list(ToolRiskLevel).index(x))
                                logger.info(
                                    f"[ToolRisk] {tool_name} upgraded to {level} " f"(fiber_count={fiber_count})"
                                )
                        if "scope" in condition:
                            scope = params.get("scope", "")
                            if scope == "all":
                                level = max(level, rule.upgrade_to, key=lambda x: list(ToolRiskLevel).index(x))
                                logger.info(f"[ToolRisk] {tool_name} upgraded to {level} " f"(scope=all)")
                    except Exception as e:
                        logger.warning(f"[ToolRisk] Dynamic rule evaluation failed: {e}")

        return level

    def requires_confirmation(self, tool_name: str, params: Optional[dict] = None) -> bool:
        """判断工具调用是否需要用户确认."""
        profile = self.get_profile(tool_name)
        if profile.confirm_required:
            return True
        risk = self.evaluate_risk(tool_name, params)
        return risk == ToolRiskLevel.HIGH

    def register_profile(self, profile: ToolRiskProfile) -> None:
        """注册/更新工具风险配置."""
        self._profiles[profile.tool_name] = profile
        logger.info(f"[ToolRisk] Registered {profile.tool_name}: {profile.risk_level.value}")

    def add_dynamic_rule(self, rule: DynamicRiskRule) -> None:
        """添加动态风险评估规则."""
        self._dynamic_rules.append(rule)

    def audit_log(self, tool_name: str, risk_level: ToolRiskLevel) -> dict:
        """生成审计日志条目."""
        return {
            "tool_name": tool_name,
            "risk_level": risk_level.value,
            "timestamp": __import__("time").time(),
            "profile": self.get_profile(tool_name).model_dump(),
        }


# =============================================================================
# 单例
# =============================================================================

_engine: Optional[ToolRiskEngine] = None


def get_tool_risk_engine() -> ToolRiskEngine:
    global _engine
    if _engine is None:
        _engine = ToolRiskEngine()
        # 注册默认动态规则
        _engine.add_dynamic_rule(
            DynamicRiskRule(
                tool_name="batch_spanloss_query",
                condition="fiber_count > 20",
                upgrade_to=ToolRiskLevel.HIGH,
            )
        )
        _engine.add_dynamic_rule(
            DynamicRiskRule(
                tool_name="batch_performance_query",
                condition="fiber_count > 20",
                upgrade_to=ToolRiskLevel.HIGH,
            )
        )
        _engine.add_dynamic_rule(
            DynamicRiskRule(
                tool_name="export_spanloss_report",
                condition="scope == 'all'",
                upgrade_to=ToolRiskLevel.HIGH,
            )
        )
        _engine.add_dynamic_rule(
            DynamicRiskRule(
                tool_name="export_performance_report",
                condition="scope == 'all'",
                upgrade_to=ToolRiskLevel.HIGH,
            )
        )
    return _engine
