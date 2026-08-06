"""
v8 核心数据模型.

ExecutionPlan: Lead Router 的输出，驱动三层 Agent 执行
AgentResult: 每个 Agent 的统一返回格式
LoopContext: Collection ↔ Analysis 循环上下文
V8State: v8 图的顶层状态
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentLayer(str, Enum):
    """三层能力 Agent 标识."""

    COLLECTION = "collection"
    ANALYSIS = "analysis"
    EXPRESSION = "expression"


class ExecutionPlan(BaseModel):
    """
    Lead Router 输出的执行计划.

    由 Skill YAML 的 routing + tools + judgment 字段解析而来。
    驱动 Orchestrator 分派任务给三层 Agent。
    """

    # 场景标识
    scenario_id: str = ""
    intent: str = ""
    confidence: float = 0.0
    match_type: str = "rule"  # "rule" | "llm" | "default"

    # Collection Agent 指令
    tools: list[str] = Field(default_factory=list)
    tool_params_hint: dict[str, Any] = Field(default_factory=dict)

    # Analysis Agent 指令
    judgment_rules: list[str] = Field(default_factory=list)
    threshold_refs: list[str] = Field(default_factory=list)
    analysis_mode: str = "rule_first"  # "rule_first" | "llm_only" | "rule_only"

    # Expression Agent 指令
    output_format: str = "narrative"  # "narrative" | "table" | "report" | "raw"
    output_template: str = ""

    # 循环控制
    max_loop_rounds: int = 3

    # 原始 Skill 元数据（透传）
    skill_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """每个 Agent 的统一返回格式."""

    layer: AgentLayer
    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    # 循环信号
    needs_more_data: bool = False
    additional_query: Optional[dict[str, Any]] = None
    # 度量
    llm_calls: int = 0
    latency_ms: float = 0.0


class LoopContext(BaseModel):
    """Collection ↔ Analysis 循环上下文."""

    round: int = 0
    max_rounds: int = 3
    collection_results: list[dict[str, Any]] = Field(default_factory=list)
    analysis_verdicts: list[dict[str, Any]] = Field(default_factory=list)
    terminated_reason: str = ""  # "complete" | "max_rounds" | "no_progress"


class V8State(BaseModel):
    """v8 图的顶层状态."""

    # 输入
    user_input: str = ""
    trace_id: str = ""
    session_id: str = ""

    # Lead Router 输出
    execution_plan: Optional[ExecutionPlan] = None
    normalized_params: dict[str, Any] = Field(default_factory=dict)

    # 循环上下文
    loop_context: LoopContext = Field(default_factory=LoopContext)

    # 各 Agent 最新结果
    collection_result: Optional[AgentResult] = None
    analysis_result: Optional[AgentResult] = None
    expression_result: Optional[AgentResult] = None

    # 最终输出
    final_response: str = ""
    final_status: str = ""

    # 治理
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
    total_llm_calls: int = 0
