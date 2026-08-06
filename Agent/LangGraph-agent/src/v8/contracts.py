"""
v8 Agent 间数据契约 — Typed Schema.

禁止裸字符串跨 Agent 传递。每个 Agent 的输入/输出都有明确的 Pydantic 类型。
Collection → Analysis: CollectionPayload
Analysis → Expression: AnalysisVerdict
Expression → Orchestrator: ExpressionOutput
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Collection → Analysis 契约
# =============================================================================


class ToolCallRecord(BaseModel):
    """单次工具调用记录."""

    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: str = ""
    latency_ms: float = 0.0


class FiberMetrics(BaseModel):
    """光纤性能指标（结构化）."""

    fiber_id: int = 0
    spanloss_db: Optional[float] = None
    oop_dbm: Optional[float] = None
    iop_dbm: Optional[float] = None
    error_code: Optional[int] = None


class AlarmRecord(BaseModel):
    """告警记录."""

    alarm_id: str = ""
    alarm_type: str = ""
    severity: str = ""
    description: str = ""
    timestamp: str = ""


class ConnectionInfo(BaseModel):
    """光纤连接拓扑信息."""

    fiber_id: int = 0
    src_ne: str = ""
    dst_ne: str = ""
    src_board: str = ""
    dst_board: str = ""
    fiber_type: str = ""
    length_km: Optional[float] = None


class CollectionPayload(BaseModel):
    """
    Collection Agent 的结构化输出.

    确定性路径：直接从 HTTP API 响应解析而来（零 LLM）。
    ReAct 路径：从 LLM 工具调用结果中提取。
    """

    # 结构化指标（核心数据）
    metrics: list[FiberMetrics] = Field(default_factory=list)
    connections: list[ConnectionInfo] = Field(default_factory=list)
    alarms: list[AlarmRecord] = Field(default_factory=list)

    # 工具调用元数据
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    collection_mode: str = "deterministic"  # "deterministic" | "react"

    # 降级字段：ReAct 路径可能无法完全结构化
    raw_summary: str = ""  # 仅 ReAct 路径保留原始文本（供 regex fallback）

    @property
    def has_structured_data(self) -> bool:
        """是否有可用的结构化数据."""
        return bool(self.metrics or self.connections or self.alarms)

    @property
    def primary_metrics(self) -> Optional[FiberMetrics]:
        """获取第一条指标（单光纤场景快捷访问）."""
        return self.metrics[0] if self.metrics else None


# =============================================================================
# Analysis → Expression 契约
# =============================================================================


class Finding(BaseModel):
    """单条分析发现."""

    metric_name: str = ""
    value: Optional[float] = None
    unit: str = ""
    level: str = "NORMAL"  # NORMAL | WARNING | CRITICAL
    description: str = ""


class AnalysisVerdict(BaseModel):
    """
    Analysis Agent 的结构化输出.

    规则路径：由 ThresholdEngine 确定性生成。
    LLM 路径：由 LLM 输出解析为 typed schema。
    """

    status: str = "UNKNOWN"  # NORMAL | WARNING | CRITICAL | UNKNOWN
    findings: list[Finding] = Field(default_factory=list)
    suggestion: str = ""
    analysis_mode: str = "rule"  # "rule" | "llm"

    # 循环控制信号
    needs_more_data: bool = False
    additional_query: Optional[dict[str, Any]] = None

    # 来源数据引用（供 Expression 反幻觉校验）
    source_metrics: list[FiberMetrics] = Field(default_factory=list)

    @property
    def worst_level(self) -> str:
        """最严重的级别."""
        levels = [f.level for f in self.findings]
        if "CRITICAL" in levels:
            return "CRITICAL"
        if "WARNING" in levels:
            return "WARNING"
        if levels:
            return "NORMAL"
        return self.status


# =============================================================================
# Expression → Orchestrator 契约
# =============================================================================


class ExpressionOutput(BaseModel):
    """
    Expression Agent 的结构化输出.
    """

    response_text: str = ""
    output_format: str = "narrative"  # narrative | table | report | raw
    hallucination_errors: list[str] = Field(default_factory=list)
    degraded: bool = False  # 是否触发了降级（LLM 报告 → 模板）
