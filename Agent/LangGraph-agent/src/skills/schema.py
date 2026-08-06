"""Skill YAML 的 Pydantic 强类型模型定义。

每个 Skill YAML 文件映射为一个 SkillDefinition 实例。
加载时即验证 Schema 合法性，非法 Skill 拒绝加载。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# =============================================================================
# 触发规则
# =============================================================================


class TriggerParam(BaseModel):
    """触发规则中的参数提取定义（group 捕获 与 value 静态值 二选一）。"""

    group: Optional[int] = Field(default=None, description="正则捕获组编号")
    value: Optional[Any] = Field(default=None, description="静态参数值（无需捕获组，如断纤固定 color=RED）")
    type: Literal["int", "str", "float", "color", "int_list", "int_range"] = Field(
        default="str", description="类型转换（color 归一化为 RED/YELLOW/GREEN；"
        "int_list/int_range 用于批量光纤参数）"
    )


class TriggerRule(BaseModel):
    """触发规则：正则 + 参数提取。"""

    pattern: str = Field(description="正则表达式")
    params: dict[str, TriggerParam] = Field(default_factory=dict, description="参数提取映射")
    confidence: float = Field(default=1.0, description="置信度")
    priority: Optional[int] = Field(default=None, description="触发级优先级覆盖（None=使用 routing.priority）")


# =============================================================================
# 路由配置
# =============================================================================


class RoutingConfig(BaseModel):
    """路由配置：决定意图走哪条路径。"""

    intent: str = Field(description="意图标识")
    group: Literal["data_query", "batch", "knowledge", "report", "chitchat"] = Field(
        description="路由组"
    )
    fast_path_eligible: bool = Field(default=False, description="是否可走 Fast Path")
    template_id: str = Field(default="", description="Fast Path 模板 ID")
    priority: int = Field(default=100, description="匹配优先级（越小越先匹配，默认100）")


# =============================================================================
# 工具定义
# =============================================================================


class ToolDefinition(BaseModel):
    """工具定义：API 调用描述。"""

    id: str = Field(description="工具标识")
    endpoint: str = Field(description="API 路径（支持 {param} 占位符）")
    method: Literal["GET", "POST"] = Field(default="GET")
    timeout: float = Field(default=2.0, description="超时秒数")
    params: dict[str, str] = Field(default_factory=dict, description="请求参数")
    response_extract: dict[str, str] = Field(default_factory=dict, description="JSONPath 提取")


# =============================================================================
# 判断规则
# =============================================================================


class JudgmentCondition(BaseModel):
    """判断条件：操作符 + 阈值 + 结论。"""

    op: Literal[">", "<", "not_in_range", "contains", "==", "count_gt"] = Field(
        description="操作符"
    )
    value: str = Field(description="阈值（支持 ${CONFIG_VAR} 引用）")
    status: Literal["CRITICAL", "WARNING", "NORMAL"] = Field(description="状态")
    finding: str = Field(description="判断结论模板（支持 {value}, {percent}）")


class JudgmentDefault(BaseModel):
    """判断默认值：所有条件不满足时的兜底。"""

    status: Literal["CRITICAL", "WARNING", "NORMAL"] = Field(default="NORMAL")
    finding: str = Field(default="未发现明显异常")


class JudgmentConfig(BaseModel):
    """判断规则配置：指标提取 + 条件评估 + 建议动作。"""

    metric: str = Field(description="指标名称")
    extract_pattern: str = Field(description="从 data_summary 提取值的正则")
    conditions: list[JudgmentCondition] = Field(default_factory=list, description="条件列表（按优先级）")
    default: JudgmentDefault = Field(default_factory=JudgmentDefault)
    actions: dict[str, list[str]] = Field(default_factory=dict, description="按 status 的建议动作")


# =============================================================================
# 输出模板
# =============================================================================


class TemplateConfig(BaseModel):
    """输出模板配置。"""

    fast_path: str = Field(default="{data}", description="Fast Path 输出模板")
    status_map: dict[str, str] = Field(default_factory=dict, description="status → 状态文本")


# =============================================================================
# 测试用例
# =============================================================================


class TestCase(BaseModel):
    """Skill 测试用例：用于自动回归验证。"""

    input: str = Field(description="用户输入")
    expected_intent: str = Field(description="期望意图")
    expected_params: dict[str, Any] = Field(default_factory=dict, description="期望参数")
    expected_fast_path: bool = Field(default=False, description="期望是否走 Fast Path")


# =============================================================================
# v8 三层架构扩展配置
# =============================================================================


class V8Config(BaseModel):
    """v8 三层架构扩展配置（可选，向后兼容）."""

    analysis_mode: Literal["rule_first", "llm_only", "rule_only"] = "rule_first"
    output_format: Literal["narrative", "table", "report", "raw"] = "narrative"
    max_loop_rounds: int = Field(default=3, ge=1, le=10)
    threshold_refs: list[str] = Field(default_factory=list)


# =============================================================================
# Skill 完整定义
# =============================================================================


class SkillDefinition(BaseModel):
    """Skill 完整定义 — 一个 YAML 文件的 Pydantic 映射。

    包含一个场景的全部扩展点：
    - triggers: 触发规则 → 注册到 RuleEngine
    - routing: 路由配置 → 注册到 route_by_intent
    - tools: 工具定义 → 注册到 FastPathExecutor / DataCollector
    - judgment: 判断规则 → 注册到 JudgmentEngine
    - template: 输出模板 → 注册到 FastPathExecutor
    - collector_tools: Normal Path 工具组 → 注入 data_collector
    - test_cases: 测试用例 → 自动回归测试
    - v8: v8 三层架构扩展配置（可选）
    """

    id: str = Field(description="唯一标识（不可重复）")
    name: str = Field(description="显示名称")
    version: str = Field(default="1.0")
    description: str = Field(default="")
    author: str = Field(default="")

    triggers: list[TriggerRule] = Field(min_length=1, description="触发规则列表")
    routing: RoutingConfig = Field(description="路由配置")
    tools: list[ToolDefinition] = Field(default_factory=list, description="工具定义")
    judgment: Optional[JudgmentConfig] = Field(default=None, description="判断规则（可选）")
    template: Optional[TemplateConfig] = Field(default=None, description="输出模板（可选）")
    collector_tools: list[str] = Field(default_factory=list, description="Normal Path 工具组")
    test_cases: list[TestCase] = Field(default_factory=list, description="测试用例")
    v8: Optional[V8Config] = Field(default=None, description="v8 三层架构扩展配置")
