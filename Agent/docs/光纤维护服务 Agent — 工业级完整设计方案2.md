# 光纤维护 Agent — LangGraph 工业级实现方案

> **版本**：v7.0-LangGraph | **框架**：LangGraph 1.0.7 + LangChain 0.3.x | **日期**：2026-07-29

------

## 第一部分：架构总览与 LangGraph 映射

### 1.1 设计哲学在 LangGraph 中的落地

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   设计哲学                    LangGraph 原语映射                         │
│   ─────────                   ──────────────────                         │
│                                                                         │
│   "LLM 只做翻译"        →    Node 内调用 LLM，但 Node 逻辑是确定性的    │
│   "规则引擎前置"        →    主图第一个 Node，条件边分流                 │
│   "参数不可信"          →    独立 Node (param_gate)，不嵌入 LLM Node    │
│   "单一数据出口"        →    子图隔离，仅 data_collector 子图绑定 Tool  │
│   "受控 Loop"           →    子图内 conditional_edge 回环 + 预算计数器  │
│   "降级链"              →    conditional_edge 多级分支                  │
│   "批量并发"            →    Send() 动态扇出                            │
│   "断点续传"            →    SqliteSaver Checkpointer                   │
│   "人机协同"            →    interrupt() + Command(resume=...)          │
│   "全链路审计"          →    Runtime Context + 每个 Node 写入审计       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 系统分层与 LangGraph 图结构对应

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          主图 (Main Graph)                                │
│                          StateGraph[FiberAgentState]                      │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  入口层                                                            │ │
│  │  [START] → input_guard → rule_engine ──┬──→ fast_executor → END   │ │
│  │                                        │                           │ │
│  │                                        └──→ intent_translator      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  控制层                                                            │ │
│  │  intent_translator → param_gate ──┬──→ [追问] → interrupt → END   │ │
│  │                                   │                                │ │
│  │                                   └──→ dispatcher                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  执行层 (子图)                                                     │ │
│  │  dispatcher ──→ data_collector_subgraph                            │ │
│  │             ──→ analysis_subgraph                                  │ │
│  │             ──→ batch_subgraph (Send 并发)                         │ │
│  │             ──→ report_subgraph                                    │ │
│  │             ──→ knowledge_subgraph                                 │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  输出层                                                            │ │
│  │  [子图输出] → narrator → audit_writer → [END]                      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  横切: Checkpointer(SqliteSaver) + Runtime Context + Callbacks    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第二部分：State 设计

### 2.1 全局状态定义

**设计理由：** State 是 LangGraph 的核心。所有节点通过读写 State 通信。工业级 State 需要：① 类型安全（TypedDict）；② 可序列化（Checkpointer 要求）；③ 包含 Loop 控制字段（预算、计数器）；④ 包含审计字段。

```
┌─────────────────────────────────────────────────────────────────────────┐
│  FiberAgentState (TypedDict)                                             │
│                                                                          │
│  ═══════════════ 输入区 ═══════════════                                  │
│  │ messages: Annotated[list[BaseMessage], add_messages]                 │
│  │   // 对话历史，使用 LangGraph 内置 add_messages reducer             │
│  │   // 设计理由: 自动处理消息追加、去重、ID 分配                      │
│  │                                                                      │
│  │ user_input: str                                                      │
│  │   // 原始用户输入（未经处理）                                        │
│  │                                                                      │
│  │ request_id: str                                                      │
│  │   // 全链路追踪 ID，由网关层生成                                     │
│  │                                                                      │
│  │ user_id: str                                                         │
│  │   // 从 JWT 解析的操作员身份                                         │
│  │                                                                      │
│  ═══════════════ 路由区 ═══════════════                                  │
│  │ route_decision: Literal[                                             │
│  │     "fast_path",       // L0 规则命中                                │
│  │     "llm_path",        // 需要 LLM 意图识别                         │
│  │     "clarify",         // 需要追问                                   │
│  │     "degraded",        // 降级路径                                   │
│  │     "reject"           // 拒绝（注入攻击等）                         │
│  │ ]                                                                    │
│  │   // 设计理由: 用 Literal 约束路由决策，防止非法状态转移             │
│  │                                                                      │
│  │ matched_rule: Optional[str]                                          │
│  │   // 命中的规则名称（Fast Path 时填充）                              │
│  │                                                                      │
│  ═══════════════ 意图区 ═══════════════                                  │
│  │ intent: Optional[str]                                                │
│  │   // 识别出的意图 (spanloss_query / alarm_query / ...)               │
│  │                                                                      │
│  │ intent_confidence: float                                             │
│  │   // 意图置信度 [0.0, 1.0]                                          │
│  │                                                                      │
│  │ extracted_params: Optional[dict]                                     │
│  │   // LLM/规则引擎提取的原始参数（未校验）                           │
│  │                                                                      │
│  │ validated_params: Optional[dict]                                     │
│  │   // 经过 param_gate 校验后的参数（可直接用于 API 调用）            │
│  │                                                                      │
│  │ clarification_question: Optional[str]                                │
│  │   // 追问内容（route_decision="clarify" 时填充）                    │
│  │                                                                      │
│  ═══════════════ 执行区 ═══════════════                                  │
│  │ execution_plan: Optional[list[ToolCallSpec]]                         │
│  │   // 确定性执行计划: [{tool_name, params, timeout}]                  │
│  │                                                                      │
│  │ api_results: Optional[list[APIResult]]                               │
│  │   // API 调用结果集合                                                │
│  │                                                                      │
│  │ structured_data: Optional[dict]                                      │
│  │   // 聚合后的结构化数据（供分析/报告使用）                          │
│  │                                                                      │
│  │ batch_chunks: Optional[list[ChunkResult]]                            │
│  │   // 批量处理各 chunk 的结果摘要                                     │
│  │                                                                      │
│  ═══════════════ 分析区 ═══════════════                                  │
│  │ judgment: Optional[dict]                                             │
│  │   // 规则引擎的判断结果 {status, severity, findings, recommendations}│
│  │                                                                      │
│  │ narrative: Optional[str]                                             │
│  │   // LLM 生成的自然语言表述                                         │
│  │                                                                      │
│  │ final_response: Optional[str]                                        │
│  │   // 最终返回给用户的文本                                           │
│  │                                                                      │
│  ═══════════════ Loop 控制区 ★ ═══════════════                           │
│  │ llm_call_count: int                                                  │
│  │   // 当前任务 LLM 调用次数（每次调用 +1）                           │
│  │   // 设计理由: Loop 预算护栏，防止无限消耗                          │
│  │                                                                      │
│  │ loop_iteration: int                                                  │
│  │   // 当前 ReAct 循环轮次（仅复杂分析子图使用）                      │
│  │                                                                      │
│  │ no_progress_count: int                                               │
│  │   // 连续无进展计数（输出与上轮相同则 +1）                          │
│  │   // 设计理由: 无进展检测，防止死循环                               │
│  │                                                                      │
│  │ last_action_signature: Optional[str]                                 │
│  │   // 上一轮动作的哈希签名（用于检测重复）                           │
│  │                                                                      │
│  ═══════════════ 降级区 ═══════════════                                  │
│  │ degradation_level: Literal["L0","L1","L2","L3","L4"]                │
│  │   // 当前降级等级                                                    │
│  │                                                                      │
│  │ error_flags: list[str]                                               │
│  │   // 累积的错误标记 ["llm_timeout", "api_5xx", ...]                 │
│  │                                                                      │
│  │ cached_data: Optional[dict]                                          │
│  │   // L4 降级时从本地缓存读取的数据                                  │
│  │                                                                      │
│  ═══════════════ 审计区 ═══════════════                                  │
│  │ audit_trail: Annotated[list[dict], operator.add]                     │
│  │   // 审计事件列表，使用 operator.add reducer（追加不覆盖）          │
│  │   // 设计理由: 每个 Node 追加自己的审计记录，最终汇总               │
│  │                                                                      │
│  │ total_latency_ms: int                                                │
│  │   // 累计延迟                                                        │
│  │                                                                      │
│  │ token_usage: dict                                                    │
│  │   // {"input": int, "output": int}                                  │
│  │                                                                      │
│  ═══════════════ 配置区 ═══════════════                                  │
│  │ config: RuntimeConfig                                                │
│  │   // 运行时配置（模型选择、超时、功能开关等）                       │
│  │   // 通过 LangGraph Runtime Context 注入，不经过 State 序列化       │
│  │                                                                      │
│  └──────────────────────────────────────────────────────────────────────│
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 辅助类型定义

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ToolCallSpec (Pydantic BaseModel)                                       │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  tool_name: str          // "fiber_spanloss_query"             │     │
│  │  params: dict            // {"fiber_id": 1001}                 │     │
│  │  timeout_seconds: float  // 2.0                                │     │
│  │  retry_count: int = 2    // 最大重试次数                       │     │
│  │  idempotency_key: str    // "{request_id}_{tool_name}_{idx}"   │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  APIResult (Pydantic BaseModel)                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  tool_name: str                                                │     │
│  │  status_code: int                                              │     │
│  │  data: Optional[dict]                                          │     │
│  │  error: Optional[str]                                          │     │
│  │  latency_ms: int                                               │     │
│  │  from_cache: bool = False                                      │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ChunkResult (Pydantic BaseModel)                                        │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  chunk_index: int                                              │     │
│  │  fiber_ids: list[int]                                          │     │
│  │  summary: dict           // {count, abnormal, max_val, ...}    │     │
│  │  error: Optional[str]                                          │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  RuntimeConfig (Pydantic BaseModel) — 通过 Runtime Context 注入         │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  primary_model: str = "qwen2.5:7b"                            │     │
│  │  fallback_model: str = "qwen2.5:3b"                           │     │
│  │  emergency_model: str = "qwen2.5:1.5b"                        │     │
│  │  max_llm_calls_per_task: int = 10                             │     │
│  │  max_tokens_per_task: int = 50000                             │     │
│  │  max_react_iterations: int = 3                                │     │
│  │  api_base_url: str = "http://backend:8080"                    │     │
│  │  ws_url: str = "ws://backend:8081/ws/v1/events"              │     │
│  │  enable_rule_engine: bool = True                              │     │
│  │  enable_cache: bool = True                                    │     │
│  │  enable_audit: bool = True                                    │     │
│  └────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

**设计理由：**

- `audit_trail` 使用 `operator.add` reducer：每个节点追加自己的审计记录，不会覆盖其他节点的记录。这是 LangGraph 的 Reducer 机制的核心用法。
- `messages` 使用 `add_messages` reducer：LangGraph 内置的消息追加逻辑，自动处理 `AIMessage`、`HumanMessage`、`ToolMessage` 的 ID 分配和去重。
- `config` 不放在 State 中序列化，而是通过 Runtime Context 注入：避免配置信息被 Checkpointer 持久化（配置可能随部署变化）。

------

## 第三部分：主图拓扑设计

### 3.1 主图节点与边定义

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  [START]                                                                 │
│     │                                                                    │
│     ▼                                                                    │
│  ┌──────────────┐                                                        │
│  │ input_guard  │  输入清洗 + 注入检测 + 长度限制                        │
│  └──────┬───────┘                                                        │
│         │                                                                │
│         ▼                                                                │
│  ┌──────────────┐     route="reject"                                     │
│  │ rule_engine  │ ──────────────────────────────────→ [END] (拒绝响应)   │
│  │  (L0 规则)   │                                                        │
│  └──────┬───────┘                                                        │
│         │                                                                │
│         │ conditional_edge: route_by_rule_result                         │
│         │                                                                │
│         ├─── route="fast_path" ──→ ┌──────────────┐                     │
│         │                          │fast_executor │ → narrator → END     │
│         │                          └──────────────┘                     │
│         │                                                                │
│         └─── route="llm_path" ───→ ┌──────────────────┐                 │
│                                    │intent_translator │                  │
│                                    │  (LLM 翻译)     │                  │
│                                    └────────┬─────────┘                 │
│                                             │                            │
│                                             ▼                            │
│                                    ┌──────────────┐                     │
│                                    │  param_gate  │                     │
│                                    │  (参数关卡)  │                     │
│                                    └──────┬───────┘                     │
│                                           │                              │
│                                           │ conditional_edge:            │
│                                           │ route_by_param_result        │
│                                           │                              │
│                    ┌──────────────────────┼──────────────────────┐      │
│                    │                      │                      │      │
│                    ▼                      ▼                      ▼      │
│             route="clarify"      route="execute"        route="reject" │
│             ┌──────────┐        ┌──────────┐           → [END]        │
│             │interrupt │        │dispatcher│                           │
│             │(追问用户)│        └────┬─────┘                           │
│             └──────────┘             │                                  │
│                                      │ conditional_edge:                │
│                                      │ route_by_intent                  │
│                                      │                                  │
│              ┌───────────┬───────────┼───────────┬───────────┐         │
│              │           │           │           │           │         │
│              ▼           ▼           ▼           ▼           ▼         │
│        ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│        │  data   │ │analysis │ │  batch  │ │ report  │ │knowledge│  │
│        │collector│ │subgraph │ │subgraph │ │subgraph │ │subgraph │  │
│        │subgraph │ │         │ │(Send×N) │ │         │ │         │  │
│        └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘  │
│             │           │           │           │           │         │
│             └───────────┴───────────┴───────────┴───────────┘         │
│                                      │                                  │
│                                      ▼                                  │
│                             ┌──────────────┐                           │
│                             │   narrator   │  LLM 表述 / 模板降级     │
│                             └──────┬───────┘                           │
│                                    │                                    │
│                                    ▼                                    │
│                             ┌──────────────┐                           │
│                             │ audit_writer │  写入审计日志             │
│                             └──────┬───────┘                           │
│                                    │                                    │
│                                    ▼                                    │
│                                 [END]                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 主图构建伪代码

```
FUNCTION build_main_graph():

    builder = StateGraph(FiberAgentState)

    // ═══ 注册节点 ═══
    builder.add_node("input_guard",      input_guard_node)
    builder.add_node("rule_engine",      rule_engine_node)
    builder.add_node("fast_executor",    fast_executor_node)
    builder.add_node("intent_translator", intent_translator_node)
    builder.add_node("param_gate",       param_gate_node)
    builder.add_node("dispatcher",       dispatcher_node)
    builder.add_node("narrator",         narrator_node)
    builder.add_node("audit_writer",     audit_writer_node)

    // ═══ 注册子图 ═══
    builder.add_node("data_collector",   build_data_collector_subgraph())
    builder.add_node("analysis",         build_analysis_subgraph())
    builder.add_node("batch_processor",  build_batch_subgraph())
    builder.add_node("report_generator", build_report_subgraph())
    builder.add_node("knowledge_qa",     build_knowledge_subgraph())

    // ═══ 定义边 ═══
    builder.add_edge(START, "input_guard")
    builder.add_edge("input_guard", "rule_engine")

    // 规则引擎后的条件路由
    builder.add_conditional_edges(
        "rule_engine",
        route_by_rule_result,          // 路由函数
        {
            "fast_path":  "fast_executor",
            "llm_path":   "intent_translator",
            "reject":     END
        }
    )

    // Fast Path 直达输出
    builder.add_edge("fast_executor", "narrator")

    // LLM 路径
    builder.add_edge("intent_translator", "param_gate")

    // 参数关卡后的条件路由
    builder.add_conditional_edges(
        "param_gate",
        route_by_param_result,
        {
            "clarify":   "clarify_interrupt",   // → interrupt()
            "execute":   "dispatcher",
            "reject":    END
        }
    )

    // 追问节点（使用 interrupt）
    builder.add_node("clarify_interrupt", clarify_interrupt_node)
    builder.add_edge("clarify_interrupt", END)

    // 调度器 → 子图（条件路由）
    builder.add_conditional_edges(
        "dispatcher",
        route_by_intent,
        {
            "single_query":    "data_collector",
            "complex_analysis":"analysis",
            "batch_query":     "batch_processor",
            "report":          "report_generator",
            "knowledge":       "knowledge_qa"
        }
    )

    // 所有子图 → narrator
    builder.add_edge("data_collector",   "narrator")
    builder.add_edge("analysis",         "narrator")
    builder.add_edge("batch_processor",  "narrator")
    builder.add_edge("report_generator", "narrator")
    builder.add_edge("knowledge_qa",     "narrator")

    // narrator → audit → END
    builder.add_edge("narrator", "audit_writer")
    builder.add_edge("audit_writer", END)

    // ═══ 编译 ═══
    checkpointer = SqliteSaver.from_conn_string("./data/checkpoints/agent.db")

    graph = builder.compile(
        checkpointer = checkpointer,
        interrupt_before = ["clarify_interrupt"],  // 追问前暂停
    )

    RETURN graph
```

**设计理由：**

- **`interrupt_before=["clarify_interrupt"]`**：使用 LangGraph 的 Human-in-the-Loop 机制。当需要追问用户时，图执行暂停，等待用户回复后通过 `Command(resume=user_reply)` 恢复。这比 v5.1 的"返回追问文本然后重新开始"更高效——State 被 Checkpointer 保存，恢复时无需重新走 input_guard → rule_engine。
- **子图作为节点注册**：LangGraph 支持将编译后的子图直接作为父图的节点。子图有自己的内部 State，通过 `input`/`output` 映射与父图 State 交互。这实现了 P2（单一数据出口）的架构隔离。
- **条件边而非固定边**：`route_by_rule_result`、`route_by_param_result`、`route_by_intent` 三个条件边实现了动态路由，避免了为每种意图创建独立的线性链路。

------

## 第四部分：核心节点详细设计

### 4.1 input_guard 节点

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: input_guard                                                       │
│                                                                          │
│  职责: 安全边界检查（在 LLM 和规则引擎之前）                             │
│  耗时: <2ms                                                              │
│  LLM 调用: 无                                                            │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION input_guard_node(state, config):                      │     │
│  │                                                                │     │
│  │   user_input = state["messages"][-1].content                   │     │
│  │                                                                │     │
│  │   // 1. 长度限制                                               │     │
│  │   IF len(user_input) > 2000:                                   │     │
│  │       RETURN {                                                 │     │
│  │         route_decision: "reject",                              │     │
│  │         final_response: "输入过长，请限制在 2000 字以内",      │     │
│  │         audit_trail: [{node:"input_guard", action:"reject",    │     │
│  │                        reason:"input_too_long"}]               │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   // 2. Prompt 注入检测（正则 + 关键词）                       │     │
│  │   injection_patterns = [                                       │     │
│  │     r"忽略.*?之前.*?指令",                                     │     │
│  │     r"ignore.*?previous.*?instructions",                       │     │
│  │     r"system\s*prompt",                                        │     │
│  │     r"你现在是.*?不再是",                                      │     │
│  │   ]                                                            │     │
│  │   IF any_match(injection_patterns, user_input):                │     │
│  │       RETURN {                                                 │     │
│  │         route_decision: "reject",                              │     │
│  │         final_response: "检测到异常输入，请重新描述您的问题",  │     │
│  │         audit_trail: [{node:"input_guard", action:"reject",    │     │
│  │                        reason:"injection_detected"}]           │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   // 3. 特殊字符清理                                           │     │
│  │   cleaned = sanitize(user_input)  // 去除控制字符              │     │
│  │                                                                │     │
│  │   // 4. 对话轮次检查                                           │     │
│  │   turn_count = count_human_messages(state["messages"])         │     │
│  │   IF turn_count > 20:                                          │     │
│  │       // 截断早期消息，保留最近 10 轮                          │     │
│  │       trimmed = trim_messages(state["messages"], keep_last=10) │     │
│  │       RETURN {messages: trimmed, user_input: cleaned}          │     │
│  │                                                                │     │
│  │   RETURN {                                                     │     │
│  │     user_input: cleaned,                                       │     │
│  │     audit_trail: [{node:"input_guard", action:"pass",          │     │
│  │                    latency_ms: elapsed}]                       │     │
│  │   }                                                            │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 注入检测在规则引擎和 LLM 之前，确保恶意输入不会到达任何处理逻辑      │
│  • 消息截断防止上下文窗口溢出（7B 模型通常 32K 上下文）                 │
│  • 此节点零 LLM 调用，纯确定性代码                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 rule_engine 节点（L0）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: rule_engine                                                       │
│                                                                          │
│  职责: 用正则/关键词匹配处理 78% 的模式化查询                           │
│  耗时: <10ms                                                             │
│  LLM 调用: 无                                                            │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION rule_engine_node(state, config):                      │     │
│  │                                                                │     │
│  │   IF NOT config.enable_rule_engine:                            │     │
│  │       RETURN {route_decision: "llm_path"}                      │     │
│  │                                                                │     │
│  │   user_input = state["user_input"]                             │     │
│  │                                                                │     │
│  │   // 遍历规则注册表（按优先级排序）                            │     │
│  │   FOR rule IN rule_registry.sorted_by_priority():              │     │
│  │                                                                │     │
│  │     match = rule.pattern.match(user_input)                     │     │
│  │                                                                │     │
│  │     IF match AND match.confidence >= 0.9:                      │     │
│  │                                                                │     │
│  │       // 提取参数                                              │     │
│  │       params = rule.extractor.extract(match)                   │     │
│  │       // 例: {fiber_ids: [1001], confidence: 1.0}             │     │
│  │                                                                │     │
│  │       // 快速校验（范围检查）                                  │     │
│  │       IF NOT rule.validator.quick_check(params):               │     │
│  │           CONTINUE  // 参数非法，尝试下一条规则                │     │
│  │                                                                │     │
│  │       RETURN {                                                 │     │
│  │         route_decision: "fast_path",                           │     │
│  │         matched_rule: rule.name,                               │     │
│  │         intent: rule.intent,                                   │     │
│  │         intent_confidence: match.confidence,                   │     │
│  │         extracted_params: params,                              │     │
│  │         validated_params: params,  // 规则提取的参数已校验     │     │
│  │         audit_trail: [{                                        │     │
│  │           node: "rule_engine",                                 │     │
│  │           action: "rule_hit",                                  │     │
│  │           rule: rule.name,                                     │     │
│  │           confidence: match.confidence                         │     │
│  │         }]                                                     │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   // 无规则命中                                                │     │
│  │   RETURN {                                                     │     │
│  │     route_decision: "llm_path",                                │     │
│  │     audit_trail: [{node:"rule_engine", action:"no_match"}]     │     │
│  │   }                                                            │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 规则引擎是"主路径优化"而非"降级方案"                                │
│  • confidence >= 0.9 的阈值确保只有高确定性匹配才走 Fast Path           │
│  • 规则提取的参数已经过校验，可跳过 param_gate 的完整校验              │
│    （但 fast_executor 内部仍有断言检查）                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.3 intent_translator 节点（LLM 翻译）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: intent_translator                                                 │
│                                                                          │
│  职责: 将自然语言翻译为结构化意图（LLM 唯一职责：翻译）                 │
│  耗时: 2-4s                                                              │
│  LLM 调用: 1 次                                                          │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION intent_translator_node(state, config):                │     │
│  │                                                                │     │
│  │   // ═══ Loop 预算检查 ★ ═══                                  │     │
│  │   IF state["llm_call_count"] >= config.max_llm_calls_per_task: │     │
│  │       RETURN {                                                 │     │
│  │         route_decision: "degraded",                            │     │
│  │         degradation_level: "L3",                               │     │
│  │         final_response: "当前请求处理次数已达上限，"            │     │
│  │                         "请使用更简洁的描述重试",               │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   // ═══ 构造 Prompt ═══                                      │     │
│  │   system_prompt = load_prompt("intent_translator.md")          │     │
│  │   // 包含: 角色定义 + 意图枚举 + 术语表 + Few-shot 示例       │     │
│  │   // 包含: 硬约束 "不得计算、不得判断、不得编造"               │     │
│  │                                                                │     │
│  │   // ═══ 结构化输出 ═══                                       │     │
│  │   llm = ChatOllama(                                            │     │
│  │       model = config.primary_model,                            │     │
│  │       temperature = 0.0,                                       │     │
│  │       seed = 42,                                               │     │
│  │   )                                                            │     │
│  │                                                                │     │
│  │   structured_llm = llm.with_structured_output(                 │     │
│  │       IntentResult,    // Pydantic Schema                      │     │
│  │       method = "json_schema",                                  │     │
│  │   )                                                            │     │
│  │                                                                │     │
│  │   TRY:                                                         │     │
│  │       result = structured_llm.invoke([                         │     │
│  │           SystemMessage(content=system_prompt),                │     │
│  │           *state["messages"][-6:],  // 最近 3 轮对话           │     │
│  │           HumanMessage(content=state["user_input"]),           │     │
│  │       ])                                                       │     │
│  │                                                                │     │
│  │       RETURN {                                                 │     │
│  │         intent: result.intent,                                 │     │
│  │         intent_confidence: result.confidence,                  │     │
│  │         extracted_params: result.params,                       │     │
│  │         llm_call_count: state["llm_call_count"] + 1,          │     │
│  │         token_usage: merge_tokens(state, result.usage),        │     │
│  │         audit_trail: [{                                        │     │
│  │           node: "intent_translator",                           │     │
│  │           model: config.primary_model,                         │     │
│  │           intent: result.intent,                               │     │
│  │           confidence: result.confidence,                       │     │
│  │         }]                                                     │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   EXCEPT (TimeoutError, ConnectionError):                      │     │
│  │       // ═══ 模型降级 ═══                                     │     │
│  │       RETURN attempt_fallback_model(state, config)             │     │
│  │       // 内部逻辑:                                             │     │
│  │       //   尝试 config.fallback_model (3b)                     │     │
│  │       //   仍失败 → 尝试 config.emergency_model (1.5b)        │     │
│  │       //   仍失败 → degradation_level="L3", 纯规则兜底        │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  IntentResult (Pydantic Schema):                                         │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  intent: Literal[                                              │     │
│  │    "spanloss_query", "alarm_query", "color_stats",             │     │
│  │    "trend_query", "performance_query", "topology_query",       │     │
│  │    "health_check", "batch_query", "report_generate",           │     │
│  │    "knowledge_qa", "comparison", "root_cause_analysis"         │     │
│  │  ]                                                             │     │
│  │  confidence: float  // [0.0, 1.0]                             │     │
│  │  params: dict       // 提取的参数                              │     │
│  │  reasoning: str     // 简要推理过程（用于审计）                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • with_structured_output(method="json_schema") 强制 LLM 输出符合       │
│    Schema 的 JSON，消除自由文本解析的不确定性                            │
│  • temperature=0.0 + seed=42 最大化输出一致性                           │
│  • 只传入最近 3 轮对话（而非全部），控制 token 消耗                      │
│  • Loop 预算检查在 LLM 调用之前，防止无限消耗                           │
│  • 模型降级链 (7b→3b→1.5b→规则) 在异常处理中实现                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.4 param_gate 节点

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: param_gate                                                        │
│                                                                          │
│  职责: 参数校验 + 转换 + 缺失检测 + 歧义检测                           │
│  耗时: <5ms                                                              │
│  LLM 调用: 无                                                            │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION param_gate_node(state, config):                       │     │
│  │                                                                │     │
│  │   intent = state["intent"]                                     │     │
│  │   params = state["extracted_params"]                           │     │
│  │                                                                │     │
│  │   // 1. 查找该意图的必填参数表                                 │     │
│  │   required = REQUIRED_PARAMS[intent]                           │     │
│  │   // 例: {"alarm_query": ["board_id", "port_id"]}             │     │
│  │                                                                │     │
│  │   // 2. 必填检查                                               │     │
│  │   missing = [p for p in required if p not in params]           │     │
│  │   IF missing:                                                  │     │
│  │       question = generate_clarification(intent, missing)       │     │
│  │       // "请提供单盘编号和端口号，例如：3号盘2号口"            │     │
│  │       RETURN {                                                 │     │
│  │         route_decision: "clarify",                             │     │
│  │         clarification_question: question,                      │     │
│  │         audit_trail: [{node:"param_gate",                      │     │
│  │                        action:"missing_params",                │     │
│  │                        missing: missing}]                      │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   // 3. 类型 + 范围校验                                        │     │
│  │   FOR key, value IN params:                                    │     │
│  │       validation = validate_param(key, value, intent)          │     │
│  │       IF validation.error:                                     │     │
│  │           RETURN {                                             │     │
│  │             route_decision: "clarify",                         │     │
│  │             clarification_question: validation.error_msg,      │     │
│  │           }                                                    │     │
│  │                                                                │     │
│  │   // 4. 参数转换                                               │     │
│  │   params = transform_params(params)                            │     │
│  │   // "FIB-1001" → 1001                                        │     │
│  │   // "红色" → "RED"                                           │     │
│  │   // "最近一周" → {"start":"2026-07-22T00:00:00+08:00",      │     │
│  │   //                "end":"2026-07-29T18:47:00+08:00"}         │     │
│  │                                                                │     │
│  │   // 5. 批量上限检查                                           │     │
│  │   IF intent == "batch_query":                                  │     │
│  │       max_limit = 50 if "alarm" in params else 200             │     │
│  │       IF len(params["ids"]) > max_limit:                       │     │
│  │           params["ids"] = params["ids"][:max_limit]            │     │
│  │           params["truncated"] = True                           │     │
│  │           params["original_count"] = original_count            │     │
│  │                                                                │     │
│  │   // 6. 歧义检测                                               │     │
│  │   IF is_ambiguous(params, intent):                             │     │
│  │       RETURN {                                                 │     │
│  │         route_decision: "clarify",                             │     │
│  │         clarification_question: disambiguation_question,       │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   // 7. 全部通过                                               │     │
│  │   RETURN {                                                     │     │
│  │     route_decision: "execute",                                 │     │
│  │     validated_params: params,                                  │     │
│  │     audit_trail: [{node:"param_gate",                          │     │
│  │                    action:"validated",                         │     │
│  │                    params_summary: summarize(params)}]         │     │
│  │   }                                                            │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 纯确定性代码，零 LLM 调用                                            │
│  • 追问使用 LangGraph interrupt 机制，State 被保存，用户回复后恢复      │
│  • 参数转换在此完成，下游节点拿到的 validated_params 可直接用于 API     │
│  • 批量截断 + 标记，而非直接拒绝（用户体验更好）                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.5 dispatcher 节点

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: dispatcher                                                        │
│                                                                          │
│  职责: 根据 intent 生成确定性执行计划，路由到对应子图                   │
│  耗时: <1ms                                                              │
│  LLM 调用: 无                                                            │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION dispatcher_node(state, config):                       │     │
│  │                                                                │     │
│  │   intent = state["intent"]                                     │     │
│  │   params = state["validated_params"]                           │     │
│  │                                                                │     │
│  │   // 确定性映射表（非 LLM 决策）                               │     │
│  │   EXECUTION_MAP = {                                            │     │
│  │     "spanloss_query": {                                        │     │
│  │       "target": "single_query",                                │     │
│  │       "plan": [ToolCallSpec(                                   │     │
│  │         tool_name="fiber_spanloss_query",                      │     │
│  │         params={"fiber_id": params["fiber_ids"][0]},           │     │
│  │         timeout_seconds=2.0                                    │     │
│  │       )]                                                       │     │
│  │     },                                                         │     │
│  │     "alarm_query": {                                           │     │
│  │       "target": "single_query",                                │     │
│  │       "plan": [ToolCallSpec(                                   │     │
│  │         tool_name="alarm_query",                               │     │
│  │         params={"board_id": params["board_id"],                │     │
│  │                 "port_id": params["port_id"]},                 │     │
│  │         timeout_seconds=2.0                                    │     │
│  │       )]                                                       │     │
│  │     },                                                         │     │
│  │     "health_check": {                                          │     │
│  │       "target": "complex_analysis",                            │     │
│  │       "plan": [                                                │     │
│  │         ToolCallSpec("board_query", ...),                      │     │
│  │         ToolCallSpec("batch_fiber_performance_query", ...),    │     │
│  │         ToolCallSpec("batch_alarm_query", ...),                │     │
│  │       ]                                                        │     │
│  │     },                                                         │     │
│  │     "batch_query": {                                           │     │
│  │       "target": "batch_query",                                 │     │
│  │       "plan": "dynamic"  // 由 batch_subgraph 内部生成        │     │
│  │     },                                                         │     │
│  │     "report_generate": {                                       │     │
│  │       "target": "report",                                      │     │
│  │       "plan": "dynamic"                                        │     │
│  │     },                                                         │     │
│  │     "knowledge_qa": {                                          │     │
│  │       "target": "knowledge",                                   │     │
│  │       "plan": []                                               │     │
│  │     },                                                         │     │
│  │     "root_cause_analysis": {                                   │     │
│  │       "target": "complex_analysis",                            │     │
│  │       "plan": "react"  // 启用受控 ReAct Loop                 │     │
│  │     },                                                         │     │
│  │   }                                                            │     │
│  │                                                                │     │
│  │   mapping = EXECUTION_MAP[intent]                              │     │
│  │                                                                │     │
│  │   RETURN {                                                     │     │
│  │     execution_plan: mapping["plan"],                           │     │
│  │     route_decision: mapping["target"],                         │     │
│  │     audit_trail: [{node:"dispatcher",                          │     │
│  │                    intent: intent,                             │     │
│  │                    target: mapping["target"]}]                 │     │
│  │   }                                                            │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 确定性映射取代 ReAct Agent 的"自主选择 Tool"                        │
│  • 消除 LLM 选错 Tool 的风险                                           │
│  • 新增意图只需在映射表中添加一行                                       │
│  • "react" 标记仅对 root_cause_analysis 等复杂意图开放                  │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第五部分：子图设计

### 5.1 Data Collector 子图（唯一 API 出口）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SUBGRAPH: data_collector                                                │
│  State: DataCollectorState (子图内部状态)                                │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  [INPUT]                                                       │     │
│  │     │                                                          │     │
│  │     ▼                                                          │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │ plan_executor    │  按 execution_plan 顺序/并行调用 Tool    │     │
│  │  │                  │                                         │     │
│  │  │  FOR each tool_call IN plan:                                │     │
│  │  │    result = http_client.call(                               │     │
│  │  │      method = tool_call.method,                             │     │
│  │  │      path = tool_call.path,                                 │     │
│  │  │      params = tool_call.params,                             │     │
│  │  │      timeout = tool_call.timeout,                           │     │
│  │  │      jwt = config.jwt_token,                                │     │
│  │  │      circuit_breaker = cb,                                  │     │
│  │  │      retry = tool_call.retry_count,                         │     │
│  │  │    )                                                        │     │
│  │  │    // 断言检查 ★                                           │     │
│  │  │    ASSERT isinstance(result.params["fiber_id"], int)        │     │
│  │  │    ASSERT 0 < result.params["fiber_id"] <= 2147483647      │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │ response_parser  │  HTTP 响应 → Pydantic Model             │     │
│  │  │                  │                                         │     │
│  │  │  200 → parse_body(ResponseModel)                           │     │
│  │  │  400 → extract_error_code()                                │     │
│  │  │  404 → mark_not_found()                                    │     │
│  │  │  5xx → increment_circuit_breaker()                         │     │
│  │  │  timeout → mark_degraded()                                 │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │ cache_writer     │  异步写入本地缓存                       │     │
│  │  │                  │                                         │     │
│  │  │  IF result.success AND config.enable_cache:                 │     │
│  │  │    cache.set(key, result.data, ttl=300)                    │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │       [OUTPUT] → api_results, structured_data                  │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 子图内部无 LLM 调用，纯 HTTP + 解析                                 │
│  • 断言检查是"最后防线"，防止上游校验被绕过                            │
│  • 缓存写入是异步的，不阻塞主流程                                      │
│  • 子图通过 input/output 映射与父图 State 交互:                         │
│    input:  {execution_plan, validated_params, config}                    │
│    output: {api_results, structured_data, error_flags}                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Analysis 子图（规则判断 + 受控 ReAct Loop）★

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SUBGRAPH: analysis                                                      │
│  State: AnalysisState                                                    │
│                                                                          │
│  这是唯一包含 ReAct Loop 的子图，且仅对复杂意图开放                     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  [INPUT]                                                       │     │
│  │     │                                                          │     │
│  │     ▼                                                          │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │ rule_judgment    │  确定性规则判断（不经过 LLM）            │     │
│  │  │                  │                                         │     │
│  │  │  • spanloss > threshold → "abnormal"                       │     │
│  │  │  • color == RED → "critical"                               │     │
│  │  │  • trend: 3天连续上升 → "deteriorating"                   │     │
│  │  │  • 对比排序 → ranked_list                                  │     │
│  │  │                                                           │     │
│  │  │  输出: judgment = {status, severity, findings, recs}       │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           │ conditional_edge: need_deeper_analysis?            │     │
│  │           │                                                    │     │
│  │     ┌─────┴─────┐                                             │     │
│  │     │           │                                             │     │
│  │     ▼           ▼                                             │     │
│  │   "no"        "yes" (仅 root_cause_analysis 等)              │     │
│  │     │           │                                             │     │
│  │     │           ▼                                             │     │
│  │     │    ┌──────────────────────────────────────────────┐     │     │
│  │     │    │  ★ CONTROLLED REACT LOOP ★                  │     │     │
│  │     │    │                                              │     │     │
│  │     │    │  ┌────────────┐                              │     │     │
│  │     │    │  │ react_think│  LLM: "还需要什么数据？"    │     │     │
│  │     │    │  └─────┬──────┘                              │     │     │
│  │     │    │        │                                     │     │     │
│  │     │    │        ▼                                     │     │     │
│  │     │    │  ┌────────────┐                              │     │     │
│  │     │    │  │ react_act  │  调用 Tool 获取补充数据     │     │     │
│  │     │    │  └─────┬──────┘                              │     │     │
│  │     │    │        │                                     │     │     │
│  │     │    │        ▼                                     │     │     │
│  │     │    │  ┌────────────┐                              │     │     │
│  │     │    │  │react_observe│ 解析结果 + 更新 judgment   │     │     │
│  │     │    │  └─────┬──────┘                              │     │     │
│  │     │    │        │                                     │     │     │
│  │     │    │        │ conditional_edge: continue_loop?    │     │     │
│  │     │    │        │                                     │     │     │
│  │     │    │   ┌────┴────┐                                │     │     │
│  │     │    │   │         │                                │     │     │
│  │     │    │   ▼         ▼                                │     │     │
│  │     │    │ "yes"     "no"                               │     │     │
│  │     │    │   │         │                                │     │     │
│  │     │    │   │         └──→ 退出循环                   │     │     │
│  │     │    │   │                                          │     │     │
│  │     │    │   └──→ 回到 react_think                     │     │     │
│  │     │    │                                              │     │     │
│  │     │    │  循环终止条件 (continue_loop 函数):          │     │     │
│  │     │    │  ┌──────────────────────────────────────┐    │     │     │
│  │     │    │  │ 1. loop_iteration >= max_react (3)   │    │     │     │
│  │     │    │  │    → 强制退出                        │    │     │     │
│  │     │    │  │                                      │    │     │     │
│  │     │    │  │ 2. llm_call_count >= max_llm (10)   │    │     │     │
│  │     │    │  │    → 预算耗尽，强制退出             │    │     │     │
│  │     │    │  │                                      │    │     │     │
│  │     │    │  │ 3. no_progress_count >= 2            │    │     │     │
│  │     │    │  │    → 无进展检测，强制退出           │    │     │     │
│  │     │    │  │                                      │    │     │     │
│  │     │    │  │ 4. LLM 输出 "analysis_complete"     │    │     │     │
│  │     │    │  │    → 正常退出                        │    │     │     │
│  │     │    │  │                                      │    │     │     │
│  │     │    │  │ 5. Tool 调用全部失败                 │    │     │     │
│  │     │    │  │    → 异常退出                        │    │     │     │
│  │     │    │  └──────────────────────────────────────┘    │     │     │
│  │     │    └──────────────────────────────────────────────┘     │     │
│  │     │           │                                             │     │
│  │     └─────┬─────┘                                             │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │       [OUTPUT] → judgment, structured_data                     │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  continue_loop 条件边伪代码:                                             │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION continue_loop(state):                                 │     │
│  │                                                                │     │
│  │   // 硬上限                                                    │     │
│  │   IF state["loop_iteration"] >= state["config"].max_react:     │     │
│  │       RETURN "exit_budget"                                     │     │
│  │                                                                │     │
│  │   // LLM 调用预算                                              │     │
│  │   IF state["llm_call_count"] >= state["config"].max_llm_calls: │     │
│  │       RETURN "exit_budget"                                     │     │
│  │                                                                │     │
│  │   // 无进展检测 ★                                              │     │
│  │   current_sig = hash(state["last_action"] + state["last_obs"]) │     │
│  │   IF current_sig == state["last_action_signature"]:            │     │
│  │       no_progress = state["no_progress_count"] + 1             │     │
│  │       IF no_progress >= 2:                                     │     │
│  │           RETURN "exit_stuck"                                  │     │
│  │       RETURN "continue"  // 更新计数器后继续                   │     │
│  │                                                                │     │
│  │   // LLM 自主判断完成                                          │     │
│  │   IF state["react_decision"] == "analysis_complete":           │     │
│  │       RETURN "exit_complete"                                   │     │
│  │                                                                │     │
│  │   // Tool 全部失败                                             │     │
│  │   IF all(r.error for r in state["api_results"]):               │     │
│  │       RETURN "exit_error"                                      │     │
│  │                                                                │     │
│  │   RETURN "continue"                                            │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • ReAct Loop 仅对 root_cause_analysis / comparison 等复杂意图开放      │
│  • 三重终止保障: 轮次上限 + 预算上限 + 无进展检测                       │
│  • 无进展检测通过 action_signature 哈希比较实现                         │
│  • 即使 LLM 不输出 "analysis_complete"，硬上限也会强制终止             │
│  • 规则判断在 Loop 之前完成，Loop 只负责"补充数据"而非"做判断"        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Batch 子图（Send 并发）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SUBGRAPH: batch_processor                                               │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  [INPUT]                                                       │     │
│  │     │                                                          │     │
│  │     ▼                                                          │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │  chunk_splitter  │  将 fiber_ids 分块                      │     │
│  │  │                  │                                         │     │
│  │  │  chunk_size = 50                                           │     │
│  │  │  chunks = split(fiber_ids, chunk_size)                     │     │
│  │  │  // 200 条 → [chunk_0(50), chunk_1(50),                   │     │
│  │  │  //            chunk_2(50), chunk_3(50)]                   │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           │  ★ Send 动态扇出 ★                                │     │
│  │           │                                                    │     │
│  │           ├──→ Send("batch_worker", {chunk: chunk_0, idx: 0}) │     │
│  │           ├──→ Send("batch_worker", {chunk: chunk_1, idx: 1}) │     │
│  │           ├──→ Send("batch_worker", {chunk: chunk_2, idx: 2}) │     │
│  │           └──→ Send("batch_worker", {chunk: chunk_3, idx: 3}) │     │
│  │                                                                │     │
│  │  ┌──────────────────────────────────────────────────────┐     │     │
│  │  │  NODE: batch_worker (并发执行)                        │     │     │
│  │  │                                                      │     │     │
│  │  │  • 幂等键: {request_id}_chunk_{idx}                  │     │     │
│  │  │  • 调用: batch_fiber_spanloss_query(chunk.fiber_ids) │     │     │
│  │  │  • 输出: 仅统计摘要                                  │     │     │
│  │  │    {count:50, abnormal:3, max_val:7.2,               │     │     │
│  │  │     abnormal_ids:[1023,1067,1089]}                   │     │     │
│  │  │  • 不返回原始数据（控制 State 大小）                 │     │     │
│  │  └──────────────────────────────────────────────────────┘     │     │
│  │           │                                                    │     │
│  │           │  所有 worker 完成后汇聚                            │     │
│  │           ▼                                                    │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │   aggregator     │  纯程序化聚合（零 token）               │     │
│  │  │                  │                                         │     │
│  │  │  • 合并 4 个 chunk 摘要                                   │     │
│  │  │  • 全局统计: total=200, abnormal=12, rate=6%              │     │
│  │  │  • 排序: 按 spanloss 降序取 Top-10                       │     │
│  │  │  • 仅 Top-10 异常数据送入后续 LLM 分析                   │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │       [OUTPUT] → batch_chunks, structured_data                 │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • LangGraph Send() 实现动态并发，无需预定义 worker 数量                │
│  • 每个 worker 只返回摘要，避免 200 条原始数据撑爆 State               │
│  • aggregator 是纯程序化的（排序、计数），不需要 LLM                    │
│  • 幂等键确保 Checkpointer 恢复时不会重复调用                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.4 Knowledge 子图（RAG）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SUBGRAPH: knowledge_qa                                                  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  [INPUT]                                                       │     │
│  │     │                                                          │     │
│  │     ▼                                                          │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │   retriever      │  混合检索                                │     │
│  │  │                  │                                         │     │
│  │  │  query = state["user_input"]                               │     │
│  │  │                                                           │     │
│  │  │  // 向量检索                                              │     │
│  │  │  embeddings = OllamaEmbeddings(                            │     │
│  │  │    model = "nomic-embed-text",                             │     │
│  │  │    base_url = "http://ollama:11434",                       │     │
│  │  │  )                                                         │     │
│  │  │  // 添加前缀 "search_query: "                             │     │
│  │  │  vector_results = chromadb.similarity_search(              │     │
│  │  │    query = "search_query: " + query,                       │     │
│  │  │    k = 5,                                                  │     │
│  │  │    score_threshold = 0.5,                                  │     │
│  │  │  )                                                         │     │
│  │  │                                                           │     │
│  │  │  // BM25 关键词检索                                       │     │
│  │  │  bm25_results = bm25_retriever.search(query, k=5)         │     │
│  │  │                                                           │     │
│  │  │  // 混合排序 (Vector 0.6 + BM25 0.4)                     │     │
│  │  │  merged = reciprocal_rank_fusion(                          │     │
│  │  │    vector_results, bm25_results,                           │     │
│  │  │    weights=[0.6, 0.4]                                     │     │
│  │  │  )[:3]                                                     │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │  ┌──────────────────┐                                         │     │
│  │  │   qa_generator   │  LLM 基于检索结果回答                  │     │
│  │  │                  │                                         │     │
│  │  │  prompt = f"""                                             │     │
│  │  │    基于以下参考资料回答用户问题。                          │     │
│  │  │    如果资料中没有相关信息，明确告知用户。                  │     │
│  │  │    不得编造资料中不存在的内容。                            │     │
│  │  │                                                           │     │
│  │  │    参考资料:                                               │     │
│  │  │    {merged_docs}                                           │     │
│  │  │                                                           │     │
│  │  │    用户问题: {query}                                       │     │
│  │  │  """                                                       │     │
│  │  │                                                           │     │
│  │  │  response = llm.invoke(prompt)                             │     │
│  │  └────────┬─────────┘                                         │     │
│  │           │                                                    │     │
│  │           ▼                                                    │     │
│  │       [OUTPUT] → narrative, structured_data                    │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • nomic-embed-text 通过 Ollama 部署，与 LLM 共享 GPU                   │
│  • 前缀 "search_query:" / "search_document:" 是 nomic 官方推荐          │
│  • 混合检索 (Vector + BM25) 比纯向量检索准确率高 5-10%                 │
│  • QA 生成有严格约束："不得编造资料中不存在的内容"                      │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第六部分：输出层与横切关注点

### 6.1 narrator 节点（LLM 表述 / 模板降级）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: narrator                                                          │
│                                                                          │
│  职责: 将结构化数据翻译为运维语言（LLM 的第二项职责：表述）             │
│  耗时: 1-2s (LLM) / <10ms (模板)                                       │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION narrator_node(state, config):                         │     │
│  │                                                                │     │
│  │   // ═══ 降级检查 ═══                                         │     │
│  │   IF state["degradation_level"] IN ["L3", "L4"]:              │     │
│  │       // 纯模板输出，不调用 LLM                               │     │
│  │       template = TEMPLATES[state["intent"]]                    │     │
│  │       response = template.format(**state["structured_data"])   │     │
│  │       // "光纤 1001 衰耗: 3.2 dB (阈值≤5dB, 状态: 正常)"     │     │
│  │       RETURN {final_response: response}                        │     │
│  │                                                                │     │
│  │   // ═══ Fast Path 模板 ═══                                   │     │
│  │   IF state["route_decision"] == "fast_path":                   │     │
│  │       // 简单查询也用模板（节省 1-2s LLM 调用）              │     │
│  │       template = FAST_TEMPLATES[state["matched_rule"]]         │     │
│  │       response = template.format(**state["structured_data"])   │     │
│  │       RETURN {final_response: response}                        │     │
│  │                                                                │     │
│  │   // ═══ LLM 表述 ═══                                        │     │
│  │   // Loop 预算检查                                             │     │
│  │   IF state["llm_call_count"] >= config.max_llm_calls_per_task: │     │
│  │       // 预算耗尽，降级为模板                                  │     │
│  │       RETURN template_fallback(state)                          │     │
│  │                                                                │     │
│  │   system_prompt = load_prompt("narrator.md")                   │     │
│  │   // 硬约束:                                                   │     │
│  │   //   "不得修改任何数值"                                      │     │
│  │   //   "不得添加 judgment 中没有的判断"                        │     │
│  │   //   "不得编造建议"                                          │     │
│  │   //   "仅做: 组织语言、排列段落、添加连接词"                 │     │
│  │                                                                │     │
│  │   TRY:                                                         │     │
│  │       response = llm.invoke([                                  │     │
│  │           SystemMessage(content=system_prompt),                │     │
│  │           HumanMessage(content=format_narration_input(         │     │
│  │               judgment = state["judgment"],                    │     │
│  │               raw_data = state["structured_data"],             │     │
│  │               intent   = state["intent"],                      │     │
│  │           ))                                                   │     │
│  │       ])                                                       │     │
│  │                                                                │     │
│  │       RETURN {                                                 │     │
│  │         final_response: response.content,                      │     │
│  │         llm_call_count: state["llm_call_count"] + 1,          │     │
│  │       }                                                        │     │
│  │                                                                │     │
│  │   EXCEPT:                                                      │     │
│  │       RETURN template_fallback(state)                          │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • Fast Path 和 L3/L4 降级时不调用 LLM，直接用模板                     │
│  • 只有复杂分析/报告才需要 LLM 润色                                    │
│  • LLM 表述有严格约束，只做"语言组织"不做"判断"                       │
│  • 预算耗尽时自动降级为模板，不会阻塞                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.2 audit_writer 节点

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: audit_writer                                                      │
│                                                                          │
│  职责: 汇总审计事件，写入持久化存储                                     │
│  耗时: <5ms (异步写入)                                                  │
│  LLM 调用: 无                                                            │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION audit_writer_node(state, config):                     │     │
│  │                                                                │     │
│  │   IF NOT config.enable_audit:                                  │     │
│  │       RETURN {}                                                │     │
│  │                                                                │     │
│  │   // 汇总所有节点的审计记录                                    │     │
│  │   audit_entry = {                                              │     │
│  │     "request_id": state["request_id"],                         │     │
│  │     "user_id": state["user_id"],                               │     │
│  │     "timestamp": now_iso8601(),                                │     │
│  │     "user_input": state["user_input"],                         │     │
│  │     "processing_path": state["route_decision"],                │     │
│  │     "matched_rule": state["matched_rule"],                     │     │
│  │     "intent": state["intent"],                                 │     │
│  │     "params": state["validated_params"],                       │     │
│  │     "api_calls": [r.summary() for r in state["api_results"]],  │     │
│  │     "degradation_level": state["degradation_level"],           │     │
│  │     "llm_call_count": state["llm_call_count"],                │     │
│  │     "token_usage": state["token_usage"],                       │     │
│  │     "total_latency_ms": elapsed_since_start(),                 │     │
│  │     "node_trail": state["audit_trail"],  // 各节点记录        │     │
│  │   }                                                            │     │
│  │                                                                │     │
│  │   // 同步写入 SQLite (热存储, 7天)                             │     │
│  │   audit_db.insert(audit_entry)                                 │     │
│  │                                                                │     │
│  │   // 异步批量写入 PostgreSQL (温存储, 180天)                   │     │
│  │   audit_queue.put(audit_entry)                                 │     │
│  │                                                                │     │
│  │   RETURN {}  // 不修改 State                                   │     │
│  └────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.3 clarify_interrupt 节点（Human-in-the-Loop）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE: clarify_interrupt                                                 │
│                                                                          │
│  职责: 暂停图执行，等待用户回复                                         │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ FUNCTION clarify_interrupt_node(state, config):                │     │
│  │                                                                │     │
│  │   // 使用 LangGraph interrupt 暂停执行                        │     │
│  │   // State 被 Checkpointer 保存                               │     │
│  │   user_reply = interrupt({                                     │     │
│  │     "question": state["clarification_question"],               │     │
│  │     "options": state.get("clarification_options", []),         │     │
│  │     "examples": state.get("clarification_examples", []),       │     │
│  │   })                                                           │     │
│  │                                                                │     │
│  │   // 用户回复后，从这里恢复执行                                │     │
│  │   // user_reply 是用户的回复文本                               │     │
│  │                                                                │     │
│  │   // 将用户回复追加到 messages                                 │     │
│  │   // 重新进入 rule_engine（用户回复可能命中规则）              │     │
│  │   RETURN Command(                                              │     │
│  │     goto = "rule_engine",                                      │     │
│  │     update = {                                                 │     │
│  │       "messages": [HumanMessage(content=user_reply)],          │     │
│  │       "user_input": user_reply,                                │     │
│  │     }                                                          │     │
│  │   )                                                            │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • interrupt() 是 LangGraph 原生的 Human-in-the-Loop 机制               │
│  • State 被 Checkpointer 持久化，即使服务重启也不丢失                   │
│  • 用户回复后通过 Command(goto="rule_engine") 重新进入路由              │
│    （而非从头开始），节省 input_guard 的重复执行                        │
│  • 追问最多 2 轮（由 clarify_count 计数器控制，超过则输出格式提示）     │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第七部分：降级机制在图中的体现

### 7.1 降级状态机

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  降级不是独立的"降级图"，而是嵌入在每个节点的条件分支中                 │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  intent_translator 节点内部:                                   │     │
│  │  ┌──────────┐    超时/错误    ┌──────────┐    超时/错误       │     │
│  │  │ 7b 模型  │ ─────────────→ │ 3b 模型  │ ─────────────→     │     │
│  │  │ (L1)     │               │ (L2)     │                    │     │
│  │  └──────────┘               └──────────┘                    │     │
│  │                                              ┌──────────┐   │     │
│  │                                              │ 1.5b模型 │   │     │
│  │                                              │ (L2.5)   │   │     │
│  │                                              └────┬─────┘   │     │
│  │                                                   │ 超时    │     │
│  │                                                   ▼         │     │
│  │                                            ┌──────────┐     │     │
│  │                                            │ 纯规则   │     │     │
│  │                                            │ (L3)     │     │     │
│  │                                            └──────────┘     │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  data_collector 子图内部:                                      │     │
│  │  ┌──────────┐    5xx/超时    ┌──────────┐    熔断 OPEN        │     │
│  │  │ API 调用 │ ─────────────→ │ 退避重试 │ ─────────────→      │     │
│  │  │ (正常)   │               │ (2次)    │                     │     │
│  │  └──────────┘               └──────────┘                     │     │
│  │                                              ┌──────────┐    │     │
│  │                                              │ 读缓存   │    │     │
│  │                                              │ (L4)     │    │     │
│  │                                              └──────────┘    │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  narrator 节点内部:                                            │     │
│  │  ┌──────────┐    LLM 不可用    ┌──────────┐                   │     │
│  │  │ LLM 表述│ ───────────────→ │ 模板输出 │                   │     │
│  │  │ (正常)  │                  │ (L3)     │                   │     │
│  │  └──────────┘                  └──────────┘                   │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 降级逻辑分散在各节点内部，而非集中管理                               │
│  • 每个节点自己知道如何降级（单一职责）                                 │
│  • 降级状态通过 State["degradation_level"] 传递                         │
│  • 下游节点根据 degradation_level 调整行为                              │
│    （如 narrator 在 L3/L4 时跳过 LLM）                                 │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 降级恢复探测（后台任务）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  BACKGROUND: degradation_recovery_probe                                  │
│                                                                          │
│  独立于主图的后台协程，每 30s 执行一次                                  │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ ASYNC FUNCTION recovery_probe_loop():                          │     │
│  │                                                                │     │
│  │   WHILE True:                                                  │     │
│  │     AWAIT sleep(30)                                            │     │
│  │                                                                │     │
│  │     current_level = get_current_degradation_level()            │     │
│  │                                                                │     │
│  │     IF current_level == "L4":                                  │     │
│  │       // 探测后端                                              │     │
│  │       IF await health_check("/api/v1/health") == 200:          │     │
│  │         consecutive_ok += 1                                    │     │
│  │         IF consecutive_ok >= 3:                                │     │
│  │           set_degradation_level("L3")                          │     │
│  │           consecutive_ok = 0                                   │     │
│  │                                                                │     │
│  │     IF current_level IN ["L3", "L2"]:                         │     │
│  │       // 探测 Ollama                                           │     │
│  │       IF await ollama_health("/api/tags") == 200:              │     │
│  │         // 探测主模型                                          │     │
│  │         IF await test_llm_call(config.primary_model):          │     │
│  │           consecutive_ok += 1                                  │     │
│  │           IF consecutive_ok >= 5:                              │     │
│  │             set_degradation_level("L1")                        │     │
│  │             consecutive_ok = 0                                 │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第八部分：事件驱动与主动巡检

### 8.1 事件监听服务（独立于主图）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SERVICE: EventListener (独立进程/协程)                                  │
│                                                                          │
│  设计理由: 事件监听是"系统驱动 Agent"，不是"用户驱动 Agent"。           │
│  它独立于主图运行，但复用主图的子图来执行诊断。                         │
│                                                                          │
│  伪代码:                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ ASYNC FUNCTION event_listener():                               │     │
│  │                                                                │     │
│  │   ws = await connect(config.ws_url)                            │     │
│  │   // 订阅: alarm, fiber_color, fiber_stats                     │     │
│  │                                                                │     │
│  │   WHILE True:                                                  │     │
│  │     TRY:                                                       │     │
│  │       event = await ws.receive_json()                          │     │
│  │                                                                │     │
│  │       IF event.type == "ALARM_RAISED":                         │     │
│  │         IF event.severity == "CRITICAL":                       │     │
│  │           // 触发自动诊断                                      │     │
│  │           await trigger_auto_diagnosis(event)                  │     │
│  │         ELSE:                                                  │     │
│  │           audit_log(event)  // 仅记录                          │     │
│  │                                                                │     │
│  │       IF event.type == "COLOR_CHANGED":                        │     │
│  │         IF event.new_color == "RED":                           │     │
│  │           // 更新缓存                                          │     │
│  │           cache.update_fiber_color(event.fiber_id, "RED")     │     │
│  │           // 推送通知                                          │     │
│  │           await notify_operators(event)                        │     │
│  │                                                                │     │
│  │       IF event.type == "STATS_UPDATED":                        │     │
│  │         // 更新本地缓存（供 Fast Path 使用）                   │     │
│  │         cache.update_stats(event.data)                         │     │
│  │                                                                │     │
│  │     EXCEPT WebSocketDisconnect:                                │     │
│  │       // 指数退避重连: 1s → 2s → 4s → ... → 60s             │     │
│  │       await reconnect_with_backoff()                           │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ ASYNC FUNCTION trigger_auto_diagnosis(event):                  │     │
│  │                                                                │     │
│  │   // 复用主图，但使用"系统用户"身份                            │     │
│  │   result = await main_graph.ainvoke(                           │     │
│  │     {                                                          │     │
│  │       "messages": [HumanMessage(                               │     │
│  │         content=f"自动诊断: {event.fiber_id}号光纤"            │     │
│  │                 f"发生{event.severity}告警，请分析原因"        │     │
│  │       )],                                                      │     │
│  │       "user_id": "system_auto_diagnosis",                      │     │
│  │       "request_id": f"auto_{event.id}",                       │     │
│  │     },                                                         │     │
│  │     config = {"configurable": {"thread_id": f"auto_{event.id}"}}│    │
│  │   )                                                            │     │
│  │                                                                │     │
│  │   // 诊断结果推送给运维人员                                    │     │
│  │   await push_notification(result["final_response"])            │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • 事件监听独立于主图，不阻塞用户请求                                   │
│  • 自动诊断复用主图（而非另建一套），确保逻辑一致性                     │
│  • 使用 "system_auto_diagnosis" 身份，审计日志可区分人工/自动           │
│  • WebSocket 断线自动重连，指数退避防止重连风暴                         │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第九部分：LangChain 组件集成

### 9.1 LLM 提供者配置

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LLM Provider Configuration                                              │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  // 主模型                                                     │     │
│  │  primary_llm = ChatOllama(                                     │     │
│  │    model = "qwen2.5:7b",                                      │     │
│  │    base_url = "http://ollama:11434",                           │     │
│  │    temperature = 0.0,                                          │     │
│  │    seed = 42,                                                  │     │
│  │    num_ctx = 8192,       // 控制上下文窗口                     │     │
│  │    timeout = 10,         // 秒                                 │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // 降级模型                                                   │     │
│  │  fallback_llm = ChatOllama(                                    │     │
│  │    model = "qwen2.5:3b",                                      │     │
│  │    temperature = 0.0,                                          │     │
│  │    seed = 42,                                                  │     │
│  │    num_ctx = 4096,                                             │     │
│  │    timeout = 8,                                                │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // Embedding                                                  │     │
│  │  embeddings = OllamaEmbeddings(                                │     │
│  │    model = "nomic-embed-text",                                 │     │
│  │    base_url = "http://ollama:11434",                           │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // 向量库                                                     │     │
│  │  vectorstore = Chroma(                                         │     │
│  │    embedding_function = embeddings,                            │     │
│  │    persist_directory = "./data/chromadb",                      │     │
│  │    collection_name = "fiber_knowledge",                        │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // 结构化输出                                                 │     │
│  │  structured_llm = primary_llm.with_structured_output(          │     │
│  │    IntentResult,                                               │     │
│  │    method = "json_schema",                                     │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • num_ctx 限制上下文窗口，防止 7B 模型在长上下文下性能下降             │
│  • with_structured_output(method="json_schema") 比 "function_calling"   │
│    在 Ollama 上更稳定（Ollama 对 function calling 支持有限）            │
│  • Chroma 持久化到本地目录，容器重启不丢失                              │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Callbacks 集成（可观测性）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Observability Callbacks                                                 │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                                                                │     │
│  │  // LangFuse 链路追踪                                         │     │
│  │  langfuse_handler = CallbackHandler(                           │     │
│  │    public_key = "...",                                         │     │
│  │    secret_key = "...",                                         │     │
│  │    host = "http://langfuse:3000",                              │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // Prometheus 指标                                            │     │
│  │  prometheus_handler = PrometheusCallbackHandler(               │     │
│  │    registry = prometheus_registry,                             │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // 自定义审计 Callback                                        │     │
│  │  audit_handler = AuditCallbackHandler(                         │     │
│  │    audit_db = audit_db,                                        │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  │  // 注入到图调用                                               │     │
│  │  result = await graph.ainvoke(                                 │     │
│  │    input_state,                                                │     │
│  │    config = {                                                  │     │
│  │      "configurable": {"thread_id": request_id},                │     │
│  │      "callbacks": [                                            │     │
│  │        langfuse_handler,                                       │     │
│  │        prometheus_handler,                                     │     │
│  │        audit_handler,                                          │     │
│  │      ],                                                        │     │
│  │      "metadata": {                                             │     │
│  │        "user_id": user_id,                                     │     │
│  │        "request_id": request_id,                               │     │
│  │      },                                                        │     │
│  │    }                                                           │     │
│  │  )                                                             │     │
│  │                                                                │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                          │
│  设计理由:                                                               │
│  • LangGraph 的 Callbacks 机制自动追踪每个 Node 的输入/输出/耗时       │
│  • LangFuse 提供可视化 Trace 查看                                       │
│  • Prometheus 指标用于 Grafana 告警                                     │
│  • 审计 Callback 独立于业务逻辑，不侵入节点代码                         │
└─────────────────────────────────────────────────────────────────────────┘
```

------

## 第十部分：完整请求流转图（端到端）

```
用户: "帮我看看1001号光纤的衰耗"
│
▼
┌─ input_guard ─────────────────────────────────────────────────────────┐
│  长度 ✓ | 注入检测 ✓ | 清理 ✓ | 轮次 ✓                              │
│  耗时: 2ms | audit_trail += [{node:"input_guard", action:"pass"}]    │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ rule_engine ─────────────────────────────────────────────────────────┐
│  Rule #12: /查.*?(\d+)号?光纤.*?衰耗/ → 命中! conf=1.0              │
│  提取: fiber_ids=[1001]                                              │
│  route_decision = "fast_path"                                        │
│  耗时: 8ms | audit_trail += [{node:"rule_engine", rule:"#12"}]      │
└───────────────────────────────────────────────────────────────────────┘
│
│ conditional_edge: route_by_rule_result → "fast_path"
│
▼
┌─ fast_executor ───────────────────────────────────────────────────────┐
│  执行计划: [fiber_spanloss_query(fiber_id=1001)]                     │
│  HTTP: GET /api/v1/fibers/1001/spanloss → 200 {"spanloss": 3.2}     │
│  断言: isinstance(1001, int) ✓ | 0 < 1001 ≤ 2147483647 ✓           │
│  缓存: cache.set("fiber:1001:spanloss", 3.2, ttl=300)               │
│  耗时: 180ms | audit_trail += [{node:"fast_executor", api:"200"}]   │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ narrator ────────────────────────────────────────────────────────────┐
│  route_decision == "fast_path" → 使用模板（不调用 LLM）              │
│  模板: "光纤 {id} 当前衰耗值为 {val} dB，{status}（阈值≤{th}dB）。" │
│  输出: "光纤 1001 当前衰耗值为 3.2 dB，正常（阈值≤5 dB）。"         │
│  耗时: 1ms | llm_call_count = 0 (未调用 LLM!)                       │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ audit_writer ────────────────────────────────────────────────────────┐
│  写入审计: {request_id, user_id, path:"fast_path", rule:"#12",       │
│            api_calls:[...], latency:191ms, llm_calls:0, tokens:0}    │
│  耗时: 3ms                                                           │
└───────────────────────────────────────────────────────────────────────┘
│
▼
[END] → 返回用户: "光纤 1001 当前衰耗值为 3.2 dB，正常（阈值≤5 dB）。"

总耗时: ~194ms | LLM 调用: 0 次 | Token 消耗: 0
用户: "帮我分析一下为什么最近红色光纤变多了"
│
▼
┌─ input_guard ─────────────────────────────────────────────────────────┐
│  通过 | 耗时: 2ms                                                    │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ rule_engine ─────────────────────────────────────────────────────────┐
│  无规则命中 (复杂分析类查询)                                         │
│  route_decision = "llm_path"                                         │
│  耗时: 5ms                                                           │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ intent_translator ───────────────────────────────────────────────────┐
│  LLM (qwen2.5:7b):                                                  │
│  → intent = "root_cause_analysis"                                    │
│  → confidence = 0.88                                                 │
│  → params = {time_range: "最近一周", focus: "红色光纤增多"}         │
│  llm_call_count = 1                                                  │
│  耗时: 2.8s                                                          │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ param_gate ──────────────────────────────────────────────────────────┐
│  必填检查 ✓ | 时间转换: "最近一周" → ISO 8601 ✓                     │
│  route_decision = "execute"                                          │
│  耗时: 2ms                                                           │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ dispatcher ──────────────────────────────────────────────────────────┐
│  intent="root_cause_analysis" → target="complex_analysis"            │
│  plan = "react" (启用受控 ReAct Loop)                                │
│  耗时: 1ms                                                           │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ analysis_subgraph ───────────────────────────────────────────────────┐
│                                                                       │
│  ┌─ rule_judgment ──────────────────────────────────────────────┐    │
│  │  调用 data_collector 获取:                                    │    │
│  │  • fiber_stats_realtime → red=15, yellow=8                   │    │
│  │  • fiber_trend(7d) → [10,11,12,13,14,15,15]                 │    │
│  │  规则判断: 7天内 red 从 10→15，增幅 50%，趋势="恶化"        │    │
│  │  耗时: 400ms                                                 │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  │                                                                    │
│  │ need_deeper_analysis? → "yes" (root_cause_analysis)               │
│  ▼                                                                    │
│  ┌─ REACT LOOP ─────────────────────────────────────────────────┐    │
│  │                                                               │    │
│  │  Iteration 1:                                                 │    │
│  │  ┌─ react_think ─────────────────────────────────────────┐   │    │
│  │  │  LLM: "需要查看红色光纤的告警分布和性能数据"          │   │    │
│  │  │  llm_call_count = 2                                   │   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  │  ┌─ react_act ───────────────────────────────────────────┐   │    │
│  │  │  调用: colored_fibers_query(RED) → 15条               │   │    │
│  │  │  调用: batch_alarm_query(ports) → 8条告警             │   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  │  ┌─ react_observe ───────────────────────────────────────┐   │    │
│  │  │  发现: 15条红色光纤中，12条集中在 3号机房             │   │    │
│  │  │  更新 judgment: key_finding = "3号机房集中异常"       │   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  │                                                               │    │
│  │  continue_loop? → loop_iteration=1 < 3 ✓                     │    │
│  │                   no_progress=0 ✓                             │    │
│  │                   llm_calls=2 < 10 ✓                          │    │
│  │                   → "continue"                                │    │
│  │                                                               │    │
│  │  Iteration 2:                                                 │    │
│  │  ┌─ react_think ─────────────────────────────────────────┐   │    │
│  │  │  LLM: "需要查看3号机房的设备状态和环境数据"           │   │    │
│  │  │  llm_call_count = 3                                   │   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  │  ┌─ react_act ───────────────────────────────────────────┐   │    │
│  │  │  调用: board_query(ne_id=3) → 温度偏高 42°C          │   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  │  ┌─ react_observe ───────────────────────────────────────┐   │    │
│  │  │  发现: 3号机房温度 42°C (阈值 35°C)                  │   │    │
│  │  │  更新 judgment: root_cause = "3号机房温控异常"        │   │    │
│  │  │  react_decision = "analysis_complete"                 │   │    │
│  │  └───────────────────────────────────────────────────────┘   │    │
│  │                                                               │    │
│  │  continue_loop? → react_decision="analysis_complete"          │    │
│  │                   → "exit_complete"                           │    │
│  │                                                               │    │
│  └───────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  输出: judgment = {                                                   │
│    status: "abnormal",                                                │
│    severity: "warning",                                               │
│    root_cause: "3号机房温控异常(42°C>35°C)",                         │
│    findings: ["红色光纤7天增50%", "12/15条集中在3号机房"],           │
│    recommendations: ["检查3号机房空调", "安排现场巡检"]              │
│  }                                                                    │
│  耗时: ~4s | llm_call_count = 3                                      │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ narrator ────────────────────────────────────────────────────────────┐
│  LLM 表述 (llm_call_count = 4):                                     │
│  "经过分析，最近一周红色光纤从 10 条增至 15 条（增幅 50%）。         │
│   其中 12 条集中在 3 号机房。进一步排查发现 3 号机房当前温度         │
│   为 42°C，超出 35°C 的温控阈值。                                    │
│                                                                       │
│   建议措施：                                                          │
│   1. 立即检查 3 号机房空调运行状态                                   │
│   2. 安排现场巡检，确认温控设备是否正常                              │
│   3. 持续关注红色光纤数量变化趋势"                                   │
│  耗时: 1.5s                                                          │
└───────────────────────────────────────────────────────────────────────┘
│
▼
┌─ audit_writer ────────────────────────────────────────────────────────┐
│  写入: {path:"llm_path", intent:"root_cause_analysis",               │
│         llm_calls:4, react_iterations:2, latency:8300ms}            │
└───────────────────────────────────────────────────────────────────────┘
│
▼
[END]

总耗时: ~8.3s | LLM 调用: 4 次 | ReAct 循环: 2 轮
```

------

## 第十一部分：项目结构（LangGraph 版）

```
fiber-maintenance-agent/
│
├── src/
│   ├── graph/                          # ★ LangGraph 图定义
│   │   ├── main_graph.py               # 主图构建 (StateGraph)
│   │   ├── state.py                    # FiberAgentState 定义
│   │   ├── nodes/                      # 节点实现
│   │   │   ├── input_guard.py
│   │   │   ├── rule_engine.py
│   │   │   ├── fast_executor.py
│   │   │   ├── intent_translator.py
│   │   │   ├── param_gate.py
│   │   │   ├── dispatcher.py
│   │   │   ├── narrator.py
│   │   │   ├── clarify_interrupt.py
│   │   │   └── audit_writer.py
│   │   ├── subgraphs/                  # 子图
│   │   │   ├── data_collector.py
│   │   │   ├── analysis.py             # 含受控 ReAct Loop
│   │   │   ├── batch_processor.py      # 含 Send 并发
│   │   │   ├── report_generator.py
│   │   │   └── knowledge_qa.py
│   │   ├── edges/                      # 条件边路由函数
│   │   │   ├── route_by_rule.py
│   │   │   ├── route_by_param.py
│   │   │   ├── route_by_intent.py
│   │   │   └── continue_loop.py        # ReAct Loop 终止判断
│   │   └── config.py                   # RuntimeConfig
│   │
│   ├── rules/                          # L0 规则引擎
│   │   ├── registry.py
│   │   ├── matcher.py
│   │   ├── extractor.py
│   │   ├── templates.py
│   │   └── definitions/                # 规则定义
│   │       ├── spanloss_rules.py
│   │       ├── alarm_rules.py
│   │       ├── color_rules.py
│   │       └── trend_rules.py
│   │
│   ├── tools/                          # LangChain Tools (23个)
│   │   ├── topology.py
│   │   ├── board.py
│   │   ├── performance.py
│   │   ├── spanloss.py
│   │   ├── alarm.py
│   │   ├── colored.py
│   │   ├── stats.py
│   │   ├── rag.py
│   │   ├── export.py
│   │   └── _http_client.py
│   │
│   ├── llm/                            # LLM 管理
│   │   ├── provider.py                 # ChatOllama 配置
│   │   ├── fallback.py                 # 模型降级链
│   │   └── prompts/                    # Prompt 模板
│   │       ├── intent_translator.md
│   │       ├── narrator.md
│   │       ├── react_think.md
│   │       └── knowledge_qa.md
│   │
│   ├── rag/                            # RAG
│   │   ├── retriever.py                # OllamaEmbeddings + Chroma
│   │   ├── ingest.py
│   │   └── bm25.py
│   │
│   ├── events/                         # 事件驱动
│   │   ├── ws_listener.py
│   │   ├── handler.py
│   │   └── scheduler.py
│   │
│   ├── resilience/                     # 容错
│   │   ├── degradation.py
│   │   ├── circuit_breaker.py
│   │   ├── cache.py
│   │   └── recovery_probe.py
│   │
│   ├── audit/                          # 审计
│   │   ├── logger.py
│   │   ├── callback.py                 # LangGraph Callback
│   │   └── models.py
│   │
│   ├── observability/                  # 可观测
│   │   ├── langfuse_setup.py
│   │   ├── prometheus.py
│   │   └── logging.py
│   │
│   ├── gateway/                        # API 网关
│   │   ├── auth.py
│   │   ├── rate_limiter.py
│   │   └── server.py                   # FastAPI 入口
│   │
│   └── main.py                         # 应用启动
│
├── tests/
│   ├── unit/
│   │   ├── test_rule_engine.py
│   │   ├── test_param_gate.py
│   │   ├── test_continue_loop.py       # ★ Loop 终止条件测试
│   │   ├── test_degradation.py
│   │   └── test_tools.py
│   ├── integration/
│   │   ├── test_fast_path.py
│   │   ├── test_llm_path.py
│   │   ├── test_react_loop.py          # ★ ReAct Loop 集成测试
│   │   ├── test_batch_send.py
│   │   └── test_interrupt_resume.py    # ★ 追问恢复测试
│   └── e2e/
│       ├── test_param_matrix.py
│       └── test_degradation_chain.py
│
├── knowledge_base/
├── data/
│   ├── checkpoints/                    # LangGraph Checkpointer
│   ├── chromadb/                       # 向量库
│   ├── cache/                          # 本地缓存
│   └── audit/                          # 审计日志
│
├── docker-compose.yaml
├── pyproject.toml
└── Makefile
```

------

## 第十二部分：关键设计决策总结

### 12.1 LangGraph 原语选择理由

| 原语                    | 使用位置                         | 选择理由                                                 |
| ----------------------- | -------------------------------- | -------------------------------------------------------- |
| **StateGraph**          | 主图 + 所有子图                  | 类型安全的状态流转，比 AgentExecutor 更可控              |
| **TypedDict + Reducer** | FiberAgentState                  | `add_messages` 处理消息追加，`operator.add` 处理审计追加 |
| **conditional_edges**   | 规则引擎后、参数关卡后、意图路由 | 动态路由，避免为每种意图建独立链路                       |
| **Command(goto=...)**   | clarify_interrupt 恢复           | 追问后跳回 rule_engine 而非从头开始                      |
| **interrupt()**         | 追问用户                         | 原生 Human-in-the-Loop，State 被 Checkpointer 保存       |
| **Send()**              | batch_processor                  | 动态并发，chunk 数量不固定                               |
| **SqliteSaver**         | Checkpointer                     | 断点续传 + 追问恢复 + 批量任务中断恢复                   |
| **Subgraph**            | 5 个执行子图                     | 架构隔离，子图有独立 State，仅通过 input/output 交互     |
| **Runtime Context**     | RuntimeConfig                    | 配置不经过 State 序列化，避免 Checkpointer 持久化配置    |
| **Callbacks**           | 可观测 + 审计                    | 非侵入式追踪，不修改节点代码                             |

### 12.2 与 v6.0 方案的差异

| 维度       | v6.0 (概念设计)        | v7.0 (LangGraph 实现)               | 变更理由                                |
| ---------- | ---------------------- | ----------------------------------- | --------------------------------------- |
| 追问机制   | 返回追问文本，重新开始 | **interrupt() + Command(resume)**   | State 持久化，恢复无需重走全流程        |
| ReAct Loop | 概念描述               | **子图内 conditional_edge 回环**    | LangGraph 原生支持循环，无需手动管理    |
| 批量并发   | 概念描述               | **Send() 动态扇出**                 | LangGraph 原生并发，自动管理汇聚        |
| 降级       | 独立降级管理器         | **分散在各节点的条件分支**          | 每个节点自治，降低耦合                  |
| 配置       | State 字段             | **Runtime Context 注入**            | 避免配置被 Checkpointer 持久化          |
| 审计       | 独立审计模块           | **State Reducer + Callback 双通道** | Reducer 保证完整性，Callback 保证实时性 |

### 12.3 Loop 控制机制总结

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Loop 安全网（四重保障）                                                 │
│                                                                          │
│  ① 轮次硬上限: loop_iteration >= max_react_iterations (3)              │
│     → 无论 LLM 是否认为完成，强制退出                                  │
│                                                                          │
│  ② LLM 调用预算: llm_call_count >= max_llm_calls_per_task (10)        │
│     → 整个任务（含意图识别+分析+表述）的 LLM 调用总次数上限            │
│                                                                          │
│  ③ 无进展检测: no_progress_count >= 2                                   │
│     → 连续 2 轮 action_signature 相同，判定为死循环                     │
│                                                                          │
│  ④ Tool 全部失败: all(r.error for r in api_results)                     │
│     → 所有 Tool 调用都失败，继续循环无意义                              │
│                                                                          │
│  任一条件触发 → 退出 Loop → 使用已有数据生成部分结果                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

------

> **文档版本**：v7.0-LangGraph | **框架版本**：LangGraph 1.0.7 + LangChain 0.3.x
> **核心定位**：基于 LangGraph 状态图的工业级光纤运维 Agent
> **设计哲学**：Harness 驯服 Loop，规则保障确定性，LLM 只做翻译