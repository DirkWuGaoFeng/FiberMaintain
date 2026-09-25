"""
状态定义 —— 光纤维护 Agent v7.1-Final 版本。

【设计原则】
- 所有状态使用 TypedDict + LangGraph Annotated reducer
- Pydantic 模型确保结构化输出（with_structured_output）
- 状态字段命名与后端 C++ 服务对齐（int32/enum/string）

【关键模型说明】
- NormalizedParams: 强类型参数，与后端 int32/enum 严格对齐
- RuleJudgment: 程序化判断结果（零 LLM 调用）
- AnalysisVerdict: LLM 辅助分析结论（14b 模型）
- LoopRecord: 增强的循环审计记录
- MainGraphState: 完整状态，包含循环控制、叙述验证、审计跟踪

【面试知识点】
  Q: 为什么用 TypedDict 而不是 dataclass？
  A: LangGraph 要求状态是 dict-like，TypedDict 提供类型提示同时兼容 dict。
     reducer（如 operator.add）需要 dict 的 update 语义。

  Q: Annotated[list, operator.add] 是什么意思？
  A: 这是 LangGraph 的 reducer 机制，当多个节点返回同名字段时，
     用 operator.add 合并（追加）而不是覆盖。常用于消息列表、审计日志。
"""

from __future__ import annotations

import operator
import uuid
from datetime import datetime
from typing import Annotated, Literal, Optional

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# =============================================================================
# 强类型 Pydantic 模型
# 【面试知识点】Pydantic 用于：
# 1. 数据验证（类型、范围、格式）
# 2. 与 LangChain 的 with_structured_output 配合，强制 LLM 输出结构化 JSON
# =============================================================================


class NormalizedParams(BaseModel):
    """归一化参数 —— 与后端 C++ int32/enum/string 严格对齐。

    【功能说明】
    这是 ParamGate（Layer 2 验证）的输出，确保所有参数在调用后端前已验证：
    - ID 类参数必须是正整数
    - 颜色必须是枚举字符串（RED/YELLOW/GREEN）
    - 时间必须是 ISO 8601 格式

    【面试知识点】
    - 参数归一化是防御性编程的体现，避免无效参数穿透到后端
    - Literal 类型约束枚举值，Pydantic 会自动验证
    """

    fiber_ids: list[int] = Field(default_factory=list, description="Fiber IDs (positive int)")
    board_ids: list[int] = Field(default_factory=list, description="Board IDs (positive int)")
    port_ids: list[int] = Field(default_factory=list, description="Port IDs (positive int)")
    port_refs: list[dict] = Field(default_factory=list, description="[{board_id, port_id}]")
    color: Optional[Literal["RED", "YELLOW", "GREEN"]] = None
    start_time: Optional[str] = Field(default=None, description="ISO 8601 start time")
    end_time: Optional[str] = Field(default=None, description="ISO 8601 end time")
    ne_id: Optional[int] = Field(default=None, description="Network element ID")
    question: Optional[str] = Field(default=None, description="Knowledge QA question text")
    parse_failures: list[str] = Field(default_factory=list, description="Parse error messages")


class RuleJudgment(BaseModel):
    """程序化判断结果 —— 由 rule_judgment 节点生成，零 LLM 调用。

    【功能说明】
    基于阈值规则的程序化判断，是叙述员（Narrator）的输入。
    叙述员必须忠实翻译这些发现，不得修改数值或添加结论。
    """

    status: Literal["NORMAL", "WARNING", "CRITICAL"] = Field(description="Overall status")
    findings: list[str] = Field(default_factory=list, description="Programmatic findings")
    metrics: dict = Field(default_factory=dict, description="Key metrics for Narrator reference")
    suggested_actions: list[str] = Field(default_factory=list, description="Recommended actions")


class AnalysisVerdict(BaseModel):
    """分析结论 —— LLM 辅助判断（14b 模型的结构化输出）。

    【功能说明】
    分析专家（Analysis Expert）的输出，决定是否：
    - 需要补充数据（触发 ReAct 循环）
    - 数据充足可以输出结论
    """

    conclusion: str = Field(description="One-sentence conclusion")
    severity: Literal["NORMAL", "WARNING", "CRITICAL"] = Field(description="Severity level")
    evidence: list[str] = Field(default_factory=list, description="Supporting data points")
    confidence: float = Field(ge=0, le=1, description="Confidence score 0-1")
    need_more_data: bool = Field(default=False, description="Whether additional data is needed")
    additional_query: Optional[dict] = Field(default=None, description='{"reason":"...", "tool":"...", "params":{...}}')


class LoopRecord(BaseModel):
    """增强的循环审计记录 [v7.1]。

    【功能说明】
    记录每次 ReAct 循环的详细信息，用于：
    - 审计跟踪（谁触发了什么操作）
    - 无进展检测（相同 action_signature 累加）
    """

    loop_number: int = Field(description="Loop iteration number")
    reason: str = Field(description="Reason for requesting more data")
    tool_requested: str = Field(description="Tool name requested")
    action_signature: str = Field(description="MD5 hash of action+observation")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class IntentResult(BaseModel):
    """意图分类结果（通过 with_structured_output 强制 14b 模型输出）。"""

    intent: Literal[
        "single_query",
        "batch_query",
        "spanloss_analysis",
        "color_diagnosis",
        "trend_analysis",
        "health_check",
        "report_generation",
        "knowledge_qa",
        "chitchat",
    ] = Field(description="Identified user intent")
    fiber_ids: list[str] = Field(default_factory=list, description="Extracted fiber IDs")
    board_ids: list[str] = Field(default_factory=list, description="Extracted board IDs")
    port_ids: list[str] = Field(default_factory=list, description="Extracted port IDs")
    ne_id: Optional[str] = Field(default=None, description="Network element ID")
    color: Optional[str] = Field(default=None, description="Color filter")
    time_range: Optional[str] = Field(default=None, description="Time range expression")
    confidence: float = Field(ge=0, le=1, description="Classification confidence")


# =============================================================================
# 主图状态 [v7.1]
# 【面试知识点】这是整个 Agent 的「大脑」，所有节点共享此状态。
# 字段分组清晰：会话、规则、循环、数据、叙述、报告、批量、知识、降级、输出、审计
# =============================================================================


class MainGraphState(TypedDict):
    """主编排图状态 —— v7.1-Final 版本。

    【状态字段分组】
    - 会话：messages, thread_id, user_input
    - 规则引擎：rule_match, fast_path_result
    - 意图与参数：intent, intent_result, normalized_params
    - 循环控制（四重终止保障）：loop_count, llm_call_count, no_progress_count
    - 数据摘要：collected_data_summary, rule_judgment, analysis_verdict
    - 叙述验证 [v7.1]：narration, narrator_validation_passed
    - 报告：report_content, report_eval
    - 批量处理：batch_chunks, batch_results, batch_progress
    - 知识：rag_context
    - 降级：degradation_level
    - 输出：final_output, processing_path
    - 审计：request_id, audit_trail, trace_id
    """

    # === 会话 ===
    messages: Annotated[list[BaseMessage], add_messages]  # 消息列表，用 add_messages reducer 追加
    thread_id: str  # 对话线程 ID，用于多轮对话关联
    user_input: str  # 用户原始输入

    # === 用户记忆 [v7.4]（书籍 Ch3：个性偏好决定表达；可选字段，向后兼容） ===
    user_id: Optional[str]  # 用户标识（缺失时跳过偏好注入）
    user_preferences: Optional[dict]  # 注入的用户偏好（output_format/language 等）

    # === 规则引擎 ===
    rule_match: Optional[dict]  # RuleMatch 序列化结果
    fast_path_result: Optional[str]  # 快速路径直接输出（跳过 LLM）

    # === 意图与参数 ===
    intent: Optional[str]  # 识别的意图（如 single_query, batch_query）
    intent_result: Optional[dict]  # IntentResult 序列化
    raw_extractions: Optional[dict]  # 原始提取结果（未归一化）
    normalized_params: Optional[dict]  # NormalizedParams 序列化（已归一化）

    # === 循环控制（四重终止保障） ===
    loop_count: int  # 当前循环轮次
    max_loops: int  # 最大循环轮次（默认 3）
    llm_call_count: int  # LLM 调用总次数
    max_llm_calls: int  # LLM 调用预算（默认 10）
    no_progress_count: int  # 无进展计数器（相同动作签名累加）
    last_action_signature: Optional[str]  # 上次动作签名（MD5）
    loop_history: Annotated[list[dict], operator.add]  # LoopRecord 列表，追加合并

    # === 数据（仅摘要，非原始数据） ===
    collected_data_summary: Optional[str]  # 收集的数据摘要
    rule_judgment: Optional[dict]  # RuleJudgment 序列化（程序化判断）
    analysis_verdict: Optional[dict]  # AnalysisVerdict 序列化（LLM 分析）

    # === 叙述验证 [v7.1] ===
    narration: Optional[str]  # 叙述员原始输出
    narrator_validation_passed: Optional[bool]  # 数字校验是否通过

    # === 报告 ===
    report_content: Optional[str]  # 生成的报告内容
    report_eval: Optional[dict]  # 报告评估结果 {"passed": bool, "refinement_count": int}

    # === 批量处理 ===
    batch_chunks: list[dict]  # 分块任务列表
    batch_results: Annotated[list[dict], operator.add]  # 分块结果，追加合并
    batch_progress: dict  # 进度信息

    # === 知识 ===
    rag_context: list[str]  # RAG 检索的知识片段

    # === 任务上下文 [v7.2]（书籍 Ch2：任务计划/进度显式化） ===
    task_plan: Optional[str]  # 任务计划描述（代码派生，零 LLM）
    task_progress: Optional[list[str]]  # 已完成步骤列表（代码派生）

    # === 注入分层 [v7.3]（书籍 Ch2：疑似->警告留痕，强->拦截） ===
    injection_suspicion: Optional[str]  # 疑似注入说明（弱命中，未拦截）
    guard_notice: Optional[str]  # 注入防御警告（注入到后续 prompt 的提示）

    # === 降级 ===
    degradation_level: int  # 降级等级：0=正常，1-4=降级

    # === 输出 ===
    final_output: Optional[str]  # 最终输出给用户的文本
    processing_path: str  # 处理路径："fast"/"normal"/"heavy"/"degraded"/"blocked"

    # === 审计 ===
    request_id: str  # 请求唯一 ID
    audit_trail: Annotated[list[dict], operator.add]  # 审计日志，追加合并

    # === 元数据 ===
    token_budget_remaining: int  # 剩余 token 预算
    session_start_time: str  # 会话开始时间

    # === 跟踪 [v7.1] ===
    trace_id: str  # 请求级跟踪 ID，用于全链路追踪


# =============================================================================
# 子图状态
# =============================================================================


class DataCollectorState(TypedDict):
    """数据收集子图状态（ReAct Agent + ToolNode）。"""

    messages: Annotated[list[BaseMessage], add_messages]
    fiber_ids: list[int]
    query_type: str
    results: dict
    errors: list[str]
    retry_count: int


class BatchChunkState(TypedDict):
    """单个分块状态，用于 Send 派发单元。"""

    chunk_id: str
    fiber_ids: list[int]  # 每块最多 50 条
    chunk_index: int
    result: Optional[dict]
    error: Optional[str]
    idempotency_key: str


class ProactiveState(TypedDict):
    """主动诊断子图状态（事件触发，无用户交互）。"""

    event: dict
    fiber_id: Optional[int]
    collected_data: Optional[str]
    analysis: Optional[str]
    alert_message: Optional[str]
    timeout_exceeded: bool


# =============================================================================
# 默认状态工厂
# =============================================================================


def create_initial_state(
    user_message: str,
    thread_id: str = "",
    user_id: str = "",
) -> dict:
    """创建新对话轮次的初始状态。

    【参数说明】
        user_message: 用户输入文本
        thread_id: 对话线程 ID（为空时自动生成）
        user_id: 用户标识（可选，为空时回退到环境变量 FIBER_USER_ID）

    【返回值】
        符合 MainGraphState 模式的完整初始状态字典

    【设计说明】
    - 所有字段初始化为 None 或默认值
    - 生成唯一的 trace_id 用于全链路跟踪
    - 循环计数器初始化为 0，由配置文件指定上限
    """
    from ..config import MAX_LLM_CALLS, MAX_LOOPS

    # 生成 trace_id 用于请求级全链路跟踪
    trace_id = uuid.uuid4().hex[:12]

    # 用户标识（可选）：优先取调用方传入的 user_id，其次环境变量 FIBER_USER_ID
    import os as _os

    user_id = user_id or _os.environ.get("FIBER_USER_ID", "")

    return {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id or uuid.uuid4().hex[:12],
        "user_input": user_message,
        # 用户记忆 [v7.4]
        "user_id": user_id or None,
        "user_preferences": None,
        # 规则引擎
        "rule_match": None,
        "fast_path_result": None,
        # 意图与参数
        "intent": None,
        "intent_result": None,
        "raw_extractions": None,
        "normalized_params": None,
        # 循环控制
        "loop_count": 0,
        "max_loops": MAX_LOOPS,  # 从 config.py 读取，默认 3
        "llm_call_count": 0,
        "max_llm_calls": MAX_LLM_CALLS,  # 从 config.py 读取，默认 10
        "no_progress_count": 0,
        "last_action_signature": None,
        "loop_history": [],
        # 数据
        "collected_data_summary": None,
        "rule_judgment": None,
        "analysis_verdict": None,
        # 叙述员 [v7.1]
        "narration": None,
        "narrator_validation_passed": None,
        # 报告
        "report_content": None,
        "report_eval": None,
        # 批量处理
        "batch_chunks": [],
        "batch_results": [],
        "batch_progress": {},
        # 知识
        "rag_context": [],
        # 任务上下文 [v7.2]
        "task_plan": None,
        "task_progress": None,
        # 注入分层 [v7.3]
        "injection_suspicion": None,
        "guard_notice": None,
        # 降级
        "degradation_level": 0,  # 0=正常
        # 输出
        "final_output": None,
        "processing_path": "normal",
        # 审计
        "request_id": uuid.uuid4().hex[:16],
        "audit_trail": [],
        # 元数据
        "token_budget_remaining": 10000,
        "session_start_time": datetime.now().isoformat(),
        # 跟踪 [v7.1]
        "trace_id": trace_id,
    }
