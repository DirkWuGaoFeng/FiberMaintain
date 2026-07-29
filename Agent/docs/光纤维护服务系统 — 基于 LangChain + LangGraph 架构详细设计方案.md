# 光纤维护服务系统 — 基于 LangChain + LangGraph 架构详细设计方案

------

## 文档信息

| 项目     | 内容                                                         |
| -------- | ------------------------------------------------------------ |
| 文档名称 | 光纤维护服务系统 Agent 详细设计报告（LangChain + LangGraph 架构版） |
| 版本号   | v5.0-LG                                                      |
| 基线文档 | 详细设计报告 v3.2.1 + v4.0 + 接口文档 v2.2                   |
| 框架基座 | LangChain ≥ 0.3.x + LangGraph ≥ 1.0.8（2026.02）             |
| 编制日期 | 2026-07-28                                                   |
| 变更说明 | 以 LangChain + LangGraph 图编排能力为核心视角，重新组织全量设计 |

------

## 第一部分：设计总览与框架映射

### 1.1 设计目标

将光纤维护服务 Agent 的全部业务能力落地到 **LangChain + LangGraph** 的标准原语上：

- 所有业务流程通过 LangGraph **StateGraph（有向状态图）** 编排
- 所有 Agent 通过 LangGraph **Subgraph（子图）** 实现
- 所有工具通过 LangChain **@tool 装饰器 + ToolNode** 定义与执行
- 所有状态通过 LangGraph **TypedDict State + Checkpointer** 持久化
- 所有批量任务通过 LangGraph **Send 并发机制** 实现 Map-Reduce
- 所有外部数据通过 LangChain **Retriever / HTTP Client** 接入
- 所有可观测性通过 **LangSmith / LangFuse** 实现

### 1.2 核心设计原则（6 项）

| #    | 原则           | LangChain/LangGraph 映射                     |
| ---- | -------------- | -------------------------------------------- |
| P1   | Agent 不做计算 | Subgraph 节点仅做语义理解；Tool 返回原始数据 |
| P2   | 单一数据出口   | 仅 data_collector 子图绑定后端 API Tools     |
| P3   | 批量工程标准化 | Send 并发 + Checkpointer 断点续传 + 幂等键   |
| P4   | 确定性优先     | ChatOllama(temperature=0.1) + seed=42        |
| P5   | 四级容错       | Conditional Edge 降级路由 + Fallback Chain   |
| P6   | 轻量存储       | Checkpointer(SQLite) + 自定义 Memory Store   |

### 1.3 LangChain/LangGraph 原语 → 系统需求映射总表

| LangChain/LangGraph 原语   | 框架机制               | 本系统使用方式              |
| -------------------------- | ---------------------- | --------------------------- |
| **StateGraph**             | 有向状态图             | 主编排图（Lead Agent）      |
| **Subgraph**               | 嵌套子图               | 4 个 Sub-Agent 各为独立子图 |
| **Node**                   | 图节点（Python 函数）  | 意图识别/任务分解/调度/聚合 |
| **Conditional Edge**       | 条件路由               | 意图分发 + 降级路由         |
| **Send**                   | 并发派发（Map-Reduce） | 批量分块并行处理            |
| **ToolNode**               | 内置工具执行节点       | 18 个自定义 Tool 的统一执行 |
| **@tool**                  | 工具定义装饰器         | 所有后端 API 封装           |
| **ChatOllama**             | 本地 LLM Provider      | qwen2.5:7b/3b/1.5b          |
| **Checkpointer**           | 状态持久化             | SQLite（断点续传/时间旅行） |
| **Memory Store**           | 长期记忆               | SQLite 指标快照             |
| **Retriever**              | RAG 检索               | ChromaDB + BM25 混合检索    |
| **Callbacks**              | 生命周期钩子           | 可观测性/限流/审计          |
| **with_structured_output** | 结构化输出             | 意图识别/分析结论 JSON      |
| **LangSmith / LangFuse**   | 可观测平台             | Trace/Metrics/Evaluation    |
| **interrupt()**            | 人工介入               | 高危操作确认（预留）        |
| **Command**                | 节点间路由指令         | 动态子图选择                |

------

## 第二部分：系统架构设计

### 2.1 整体架构（LangGraph 视角）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户交互层                                     │
│         (LangServe API :8000 / Vue3 面板 :5173 / LangGraph Studio)  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP / WebSocket (LangServe)
┌──────────────────────────▼──────────────────────────────────────────┐
│              LangGraph Runtime (主编排图)                             │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Callbacks Pipeline (LangChain 回调链)                        │   │
│  │  ① AuthCallback → ② RateLimitCallback → ③ TracingCallback   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Main StateGraph (Lead Agent 编排图)                          │   │
│  │                                                               │   │
│  │  [START] → intent_classifier → task_decomposer                │   │
│  │       → (Conditional Edge: 意图路由)                          │   │
│  │           ├─→ data_collector_subgraph                         │   │
│  │           ├─→ analysis_subgraph                               │   │
│  │           ├─→ report_subgraph                                 │   │
│  │           ├─→ knowledge_subgraph                              │   │
│  │           └─→ batch_subgraph (Send 并发)                      │   │
│  │       → result_aggregator → [END]                             │   │
│  │                                                               │   │
│  │  Checkpointer: SqliteSaver (断点续传)                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Sub-Agent Subgraphs (4 个子图)                               │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │   │
│  │  │data_collector│ │  analysis   │ │   report    │            │   │
│  │  │  (ToolNode)  │ │  (LLM Node) │ │  (LLM+RAG)  │            │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘            │   │
│  │  ┌─────────────┐ ┌─────────────────────────────┐            │   │
│  │  │ knowledge   │ │  batch_processor            │            │   │
│  │  │  (RAG Node) │ │  (Send Map-Reduce)          │            │   │
│  │  └─────────────┘ └─────────────────────────────┘            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  LangChain Tool Layer (tools/)                                │   │
│  │  18 @tool: topology(4) + performance(2) + alarm(2)           │   │
│  │  + colored(2) + stats(2) + batch(4) + rag(2)                 │   │
│  │  + export(3) + memory(2)                                     │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼───────────────────────────────────┐   │
│  │  Data Access Layer (httpx AsyncClient)                        │   │
│  │  熔断器 │ 背压控制 │ 退避重试 │ 超时分级(2s/3s/5s)           │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼───────────────────────────────────┐   │
│  │  Memory & Persistence                                         │   │
│  │  Checkpointer(SQLite) + MemoryStore(SQLite) + ChromaDB       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Observability (LangSmith / LangFuse)                         │   │
│  │  Tracing + Metrics + Evaluation + Prompt Versioning          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│              后端业务系统 (C++ REST :8080 / WS :8081)                │
└─────────────────────────────────────────────────────────────────────┘

外部依赖:
  OLLAMA (:11434) — qwen2.5:7b / 3b / 1.5b
  ChromaDB (:8100) — RAG 向量数据库
  LangSmith / LangFuse — 可观测平台
  Prometheus (:9090) + Grafana (:3001) — 基础设施监控
```

### 2.2 LangGraph 图结构总览

```
                        ┌─────────┐
                        │  START  │
                        └────┬────┘
                             │
                    ┌────────▼────────┐
                    │ intent_classifier│  ← 结构化输出 (Pydantic)
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ task_decomposer │  ← 任务分解 + 子图选择
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌──────▼─────┐  ┌────▼────────┐
     │ 单条查询    │  │ 分析/诊断   │  │ 批量处理     │
     │ (data_     │  │ (analysis_ │  │ (batch_     │
     │ collector) │  │ subgraph)  │  │ Send并发)   │
     └────────┬───┘  └──────┬─────┘  └────┬────────┘
              │              │              │
              │       ┌──────▼─────┐       │
              │       │ report_    │       │
              │       │ subgraph   │       │
              │       └──────┬─────┘       │
              │              │              │
              └──────────────┼──────────────┘
                             │
                    ┌────────▼────────┐
                    │result_aggregator│  ← 结果聚合 + 自然语言表述
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  degradation_   │  ← 降级检查 (Conditional Edge)
                    │  check          │
                    └────────┬────────┘
                             │
                        ┌────▼────┐
                        │   END   │
                        └─────────┘
```

### 2.3 Sub-Agent 注册表（LangGraph Subgraph）

| Sub-Agent           | LangGraph 实现             | 温度 | 模型       | 绑定 Tools                |
| ------------------- | -------------------------- | ---- | ---------- | ------------------------- |
| data_collector      | Subgraph + ToolNode        | 0.0  | qwen2.5:7b | 14 个数据查询 Tools       |
| analysis_expert     | Subgraph + LLM Node        | 0.1  | qwen2.5:7b | memory_query, memory_save |
| report_generator    | Subgraph + LLM + Retriever | 0.3  | qwen2.5:7b | rag_query, export_*       |
| knowledge_assistant | Subgraph + Retriever Node  | 0.5  | qwen2.5:7b | rag_query, memory_query   |
| batch_processor     | Subgraph + Send 并发       | 0.1  | qwen2.5:7b | batch_* Tools             |

------

## 第三部分：State 设计（LangGraph 核心）

### 3.1 主图 State 定义

```python
from typing import TypedDict, Annotated, Literal, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field
import operator

# ========== 意图识别结构化输出 ==========
class IntentResult(BaseModel):
    """意图识别结果（with_structured_output 强制约束）"""
    intent: Literal[
        "single_query",      # 单条光纤查询
        "batch_query",       # 批量查询
        "spanloss_analysis", # 衰耗分析
        "color_diagnosis",   # 颜色诊断
        "trend_analysis",    # 趋势分析
        "health_check",      # 网元巡检
        "report_generation", # 报告生成
        "knowledge_qa",      # 知识问答
        "chitchat"           # 闲聊/兜底
    ] = Field(description="识别到的用户意图")
    fiber_ids: list[str] = Field(default=[], description="提取到的光纤编号列表")
    ne_id: Optional[str] = Field(default=None, description="网元编号")
    time_range: Optional[str] = Field(default=None, description="时间范围")
    confidence: float = Field(ge=0, le=1, description="置信度")

# ========== 主图 State ==========
class FiberAgentState(TypedDict):
    # 消息流（LangGraph 标准）
    messages: Annotated[list[BaseMessage], add_messages]

    # 意图与任务
    intent: Optional[IntentResult]
    task_plan: list[str]                    # 分解后的子任务列表
    current_subtask_index: int              # 当前执行到第几个子任务

    # 数据层
    fiber_data: dict                        # 光纤原始数据（Tool 返回）
    alarm_data: dict                        # 告警数据
    performance_data: dict                  # 性能数据
    stats_data: dict                        # 统计数据

    # 分析层
    analysis_result: Optional[dict]         # 分析结论
    diagnosis: Optional[str]                # 诊断文本

    # 批量层
    batch_chunks: list[dict]                # 分块任务列表
    batch_results: Annotated[list[dict], operator.add]  # Send 并发结果（reducer 合并）
    batch_progress: dict                    # 进度 {completed, total, percentage}

    # 知识层
    rag_context: list[str]                  # RAG 检索结果
    memory_context: list[dict]              # 历史记忆

    # 输出层
    final_report: Optional[str]             # 最终报告（Markdown）
    export_path: Optional[str]              # 导出文件路径

    # 控制层
    degradation_level: Literal["L1", "L2", "L3", "L4"]
    error_log: list[str]
    trace_id: str
```

### 3.2 子图 State（以 data_collector 为例）

```python
class DataCollectorState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    fiber_ids: list[str]
    query_type: Literal["single", "batch", "performance", "alarm", "stats"]
    results: dict
    errors: list[str]
    retry_count: int
```

### 3.3 批量处理 State（Send 并发专用）

```python
class BatchChunkState(TypedDict):
    """单个 Chunk 的状态（Send 派发单元）"""
    chunk_id: str
    fiber_ids: list[str]        # ≤ 50 条
    chunk_index: int
    result: Optional[dict]
    error: Optional[str]
    idempotency_key: str

class BatchAggregateState(TypedDict):
    """聚合后的批量结果"""
    total: int
    normal_count: int
    abnormal_count: int
    color_distribution: dict    # {green: n, yellow: n, red: n}
    spanloss_stats: dict        # {mean, max, min, std}
    top_anomalies: list[dict]   # Top-10 异常
    red_fibers: list[str]       # 红色光纤全量
```

------

## 第四部分：主图编排设计（StateGraph）

### 4.1 主图构建代码

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Send, Command, interrupt

def build_main_graph():
    """构建主编排图"""

    graph = StateGraph(FiberAgentState)

    # ===== 注册节点 =====
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("task_decomposer", task_decomposer_node)
    graph.add_node("data_collector", data_collector_subgraph)
    graph.add_node("analysis_expert", analysis_expert_subgraph)
    graph.add_node("report_generator", report_generator_subgraph)
    graph.add_node("knowledge_assistant", knowledge_assistant_subgraph)
    graph.add_node("batch_dispatcher", batch_dispatcher_node)    # Send 派发
    graph.add_node("batch_worker", batch_worker_node)            # Send 执行
    graph.add_node("batch_aggregator", batch_aggregator_node)    # 聚合
    graph.add_node("result_aggregator", result_aggregator_node)
    graph.add_node("degradation_handler", degradation_handler_node)

    # ===== 注册边 =====
    graph.add_edge(START, "intent_classifier")
    graph.add_edge("intent_classifier", "task_decomposer")

    # 条件路由：根据意图分发到不同子图
    graph.add_conditional_edges(
        "task_decomposer",
        route_by_intent,  # 路由函数
        {
            "single_query": "data_collector",
            "batch_query": "batch_dispatcher",
            "spanloss_analysis": "data_collector",
            "color_diagnosis": "data_collector",
            "trend_analysis": "data_collector",
            "health_check": "data_collector",
            "report_generation": "report_generator",
            "knowledge_qa": "knowledge_assistant",
            "chitchat": "result_aggregator",
        }
    )

    # 数据收集后 → 分析
    graph.add_edge("data_collector", "analysis_expert")
    # 分析后 → 报告（条件）
    graph.add_conditional_edges(
        "analysis_expert",
        route_after_analysis,
        {
            "need_report": "report_generator",
            "direct_answer": "result_aggregator",
        }
    )
    graph.add_edge("report_generator", "result_aggregator")
    graph.add_edge("knowledge_assistant", "result_aggregator")

    # 批量：Send 并发
    graph.add_conditional_edges("batch_dispatcher", dispatch_chunks)  # 返回 Send 列表
    graph.add_edge("batch_worker", "batch_aggregator")
    graph.add_edge("batch_aggregator", "analysis_expert")

    # 结果聚合 → 降级检查 → 结束
    graph.add_edge("result_aggregator", "degradation_handler")
    graph.add_conditional_edges(
        "degradation_handler",
        check_degradation,
        {
            "normal": END,
            "fallback": "degradation_handler",  # 循环重试
        }
    )

    # ===== 编译（含 Checkpointer） =====
    checkpointer = SqliteSaver.from_conn_string("data/checkpoints.db")
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["batch_dispatcher"],  # 批量前可人工确认（预留）
    )
```

### 4.2 意图路由函数

```python
def route_by_intent(state: FiberAgentState) -> str:
    """条件边：根据意图路由到对应子图"""
    intent = state["intent"]

    if intent is None or intent.confidence < 0.6:
        return "chitchat"

    # 分析/诊断类：先收集数据再分析
    if intent.intent in ["spanloss_analysis", "color_diagnosis",
                         "trend_analysis", "health_check"]:
        return "single_query"  # 走 data_collector → analysis 链路

    return intent.intent
```

### 4.3 意图识别节点（结构化输出）

```python
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

llm_primary = ChatOllama(
    model="qwen2.5:7b",
    temperature=0.0,
    base_url="http://ollama:11434",
)

intent_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是光纤维护系统的意图识别器。
根据用户输入，识别意图并提取关键参数。
光纤编号格式: FIB-XXXX（4位数字）。
仅输出 JSON，不要解释。"""),
    ("human", "{user_input}"),
])

intent_chain = intent_prompt | llm_primary.with_structured_output(IntentResult)

async def intent_classifier_node(state: FiberAgentState) -> dict:
    """意图识别节点"""
    user_msg = state["messages"][-1].content
    result: IntentResult = await intent_chain.ainvoke({"user_input": user_msg})
    return {"intent": result}
```

------

## 第五部分：Sub-Agent 子图设计

### 5.1 data_collector 子图

```python
from langgraph.prebuilt import ToolNode, create_react_agent

# 仅 data_collector 绑定后端 API Tools（P2 原则）
data_tools = [
    fiber_connection_query,
    batch_fiber_connection_query,
    board_query,
    batch_board_query,
    fiber_performance_query,
    batch_fiber_performance_query,
    fiber_spanloss_query,
    batch_fiber_spanloss_query,
    colored_fibers_query,
    all_colored_fibers_query,
    fiber_stats_query,
    fiber_trend_query,
    alarm_query,
    batch_alarm_query,
]

def build_data_collector_subgraph():
    """数据收集子图：ReAct Agent + ToolNode"""
    return create_react_agent(
        model=ChatOllama(model="qwen2.5:7b", temperature=0.0),
        tools=data_tools,
        prompt=DATA_COLLECTOR_SYSTEM_PROMPT,
        # 最大工具调用轮次（防止无限循环）
        recursion_limit=10,
    )

data_collector_subgraph = build_data_collector_subgraph()
```

### 5.2 analysis_expert 子图

```python
def build_analysis_subgraph():
    """分析专家子图：LLM 推理 + 记忆读写"""
    graph = StateGraph(DataCollectorState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("save_memory", save_memory_node)

    graph.add_edge(START, "load_memory")
    graph.add_edge("load_memory", "analyze")
    graph.add_edge("analyze", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile()

async def analyze_node(state: FiberAgentState) -> dict:
    """核心分析节点（温度 0.1，确定性优先）"""
    llm = ChatOllama(model="qwen2.5:7b", temperature=0.1, seed=42)

    prompt = ChatPromptTemplate.from_messages([
        ("system", ANALYSIS_SYSTEM_PROMPT),
        ("human", """
## 光纤数据
{fiber_data}

## 历史记忆
{memory_context}

## 分析要求
请对以上数据进行衰耗/颜色/趋势分析，输出结构化结论。
"""),
    ])

    chain = prompt | llm.with_structured_output(AnalysisResult)
    result = await chain.ainvoke({
        "fiber_data": format_fiber_data(state["fiber_data"]),
        "memory_context": format_memory(state["memory_context"]),
    })
    return {"analysis_result": result.dict(), "diagnosis": result.summary}
```

### 5.3 report_generator 子图

```python
def build_report_subgraph():
    """报告生成子图：RAG 增强 + LLM 生成 + 导出"""
    graph = StateGraph(FiberAgentState)

    graph.add_node("rag_retrieve", rag_retrieve_node)
    graph.add_node("generate_report", generate_report_node)
    graph.add_node("export_file", export_file_node)

    graph.add_edge(START, "rag_retrieve")
    graph.add_edge("rag_retrieve", "generate_report")
    graph.add_conditional_edges(
        "generate_report",
        lambda s: "export" if s.get("export_path") else END,
        {"export": "export_file", "end": END}
    )
    graph.add_edge("export_file", END)

    return graph.compile()
```

### 5.4 knowledge_assistant 子图

```python
def build_knowledge_subgraph():
    """知识问答子图：纯 RAG 检索 + LLM 回答"""
    graph = StateGraph(FiberAgentState)

    graph.add_node("retrieve", rag_retrieve_node)
    graph.add_node("answer", knowledge_answer_node)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)

    return graph.compile()
```

------

## 第六部分：LangChain Tool 层详细设计

### 6.1 Tool 目录结构

```
src/tools/
├── __init__.py                 # 统一导出
├── topology_tools.py           # 4 tools
├── performance_tools.py        # 2 tools
├── alarm_tools.py              # 2 tools
├── colored_tools.py            # 2 tools
├── stats_tools.py              # 2 tools
├── batch_tools.py              # 4 tools
├── rag_tools.py                # 2 tools
├── export_tools.py             # 3 tools
├── memory_tools.py             # 2 tools
└── _http_client.py             # 共享 HTTP 客户端（熔断/重试/背压）
```

### 6.2 Tool 定义规范（@tool 装饰器）

```python
# src/tools/topology_tools.py
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from ._http_client import fiber_http_client

class FiberQueryInput(BaseModel):
    fiber_id: str = Field(description="光纤编号，格式 FIB-XXXX")

@tool(args_schema=FiberQueryInput)
async def fiber_connection_query(fiber_id: str) -> str:
    """查询单条连纤信息（网元间光纤连接）。
    返回: 连纤详情 JSON（src_board, dst_board, color, scene_type）"""
    return await fiber_http_client.get(
        f"/api/v1/topology/fibers/{fiber_id}",
        timeout=2.0
    )

class BatchFiberQueryInput(BaseModel):
    fiber_ids: list[str] = Field(description="光纤编号列表（≤50条/块）")
    chunk_id: str = Field(description="块唯一标识（幂等键）")

@tool(args_schema=BatchFiberQueryInput)
async def batch_fiber_connection_query(fiber_ids: list[str], chunk_id: str) -> str:
    """批量查询连纤信息（分块，每块≤50条）。
    返回: 批量结果 JSON（含 found/error_message 标记）"""
    return await fiber_http_client.post(
        "/api/v1/topology/fibers/batch",
        json={"fiber_ids": fiber_ids, "chunk_id": chunk_id},
        timeout=5.0
    )
```

### 6.3 Tool → 后端 API 完整映射表

| LangChain Tool                | 后端 REST API                         | 超时 | 所属子图             |
| ----------------------------- | ------------------------------------- | ---- | -------------------- |
| fiber_connection_query        | GET /api/v1/topology/fibers/{id}      | 2s   | data_collector       |
| batch_fiber_connection_query  | POST /api/v1/topology/fibers/batch    | 5s   | data_collector       |
| board_query                   | GET /api/v1/boards/{id}               | 2s   | data_collector       |
| batch_board_query             | POST /api/v1/boards/batch             | 5s   | data_collector       |
| fiber_performance_query       | GET /api/v1/fibers/{id}/performance   | 2s   | data_collector       |
| batch_fiber_performance_query | POST /api/v1/fibers/performance/batch | 5s   | data_collector       |
| fiber_spanloss_query          | GET /api/v1/fibers/{id}/spanloss      | 2s   | data_collector       |
| batch_fiber_spanloss_query    | POST /api/v1/fibers/spanloss/batch    | 5s   | data_collector       |
| colored_fibers_query          | GET /api/v1/fibers/colored?color=X    | 2s   | data_collector       |
| all_colored_fibers_query      | GET /api/v1/fibers/colored/all        | 3s   | data_collector       |
| fiber_stats_query             | GET /api/v1/fibers/stats/realtime     | 2s   | data_collector       |
| fiber_trend_query             | GET /api/v1/fibers/stats/trend        | 3s   | data_collector       |
| alarm_query                   | GET /api/v1/alarms/current            | 2s   | data_collector       |
| batch_alarm_query             | POST /api/v1/alarms/batch             | 5s   | data_collector       |
| rag_query                     | ChromaDB 内部                         | 3s   | report / knowledge   |
| rag_search                    | ChromaDB 内部                         | 3s   | report / knowledge   |
| export_pdf                    | 本地 reportlab                        | 10s  | report_generator     |
| export_excel                  | 本地 openpyxl                         | 10s  | report_generator     |
| export_csv                    | 本地 csv                              | 5s   | report_generator     |
| memory_save                   | SQLite 异步写入                       | 1s   | analysis_expert      |
| memory_query                  | SQLite 查询                           | 1s   | analysis / knowledge |

### 6.4 共享 HTTP 客户端（熔断/重试/背压）

```python
# src/tools/_http_client.py
import httpx
import asyncio
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class FiberHttpClient:
    """带熔断/重试/背压的 HTTP 客户端"""

    def __init__(self, base_url: str = "http://fiber-backend:8080"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url)
        # 熔断器
        self.circuit_state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = 5
        self.cooldown_seconds = 30
        # 背压
        self.error_rate = 0.0
        self.concurrency = 5
        self.inter_request_delay = 0.2

    async def get(self, path: str, timeout: float = 2.0) -> str:
        return await self._request("GET", path, timeout=timeout)

    async def post(self, path: str, json: dict, timeout: float = 5.0) -> str:
        return await self._request("POST", path, json=json, timeout=timeout)

    async def _request(self, method, path, **kwargs) -> str:
        # 1. 熔断检查
        if self.circuit_state == CircuitState.OPEN:
            raise CircuitOpenError("后端服务熔断中")

        # 2. 背压延迟
        await asyncio.sleep(self.inter_request_delay)

        # 3. 重试（5xx → 退避重试 2 次）
        for attempt in range(3):
            try:
                resp = await self.client.request(method, path, **kwargs)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(...)
                self._record_success()
                return resp.text
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                self._record_failure()
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    raise

    def _record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.circuit_state = CircuitState.OPEN
            # 启动冷却定时器
            asyncio.create_task(self._cooldown())

    async def _cooldown(self):
        await asyncio.sleep(self.cooldown_seconds)
        self.circuit_state = CircuitState.HALF_OPEN
        self.failure_count = 0

fiber_http_client = FiberHttpClient()
```

------

## 第七部分：批量处理引擎（Send 并发 + Checkpointer）

### 7.1 LangGraph Send 机制实现 Map-Reduce

```python
from langgraph.types import Send

def batch_dispatcher_node(state: FiberAgentState) -> list[Send]:
    """
    批量派发节点：将 N 条光纤 ID 分块，通过 Send 并发派发。
    LangGraph 会自动并行执行所有 Send 目标节点。
    """
    fiber_ids = state["intent"].fiber_ids
    assert len(fiber_ids) <= 200, "超出批量上限 200"

    chunk_size = 50
    chunks = [
        fiber_ids[i:i+chunk_size]
        for i in range(0, len(fiber_ids), chunk_size)
    ]

    # 生成 Send 列表 → LangGraph 并发执行 batch_worker
    sends = []
    for idx, chunk in enumerate(chunks):
        chunk_id = f"{state['trace_id']}_chunk_{idx}"
        sends.append(
            Send(
                "batch_worker",
                {
                    "chunk_id": chunk_id,
                    "fiber_ids": chunk,
                    "chunk_index": idx,
                    "idempotency_key": chunk_id,
                    "result": None,
                    "error": None,
                }
            )
        )
    return sends


async def batch_worker_node(state: BatchChunkState) -> dict:
    """
    批量工作节点：处理单个 Chunk。
    由 Send 并发调用，LangGraph 自动管理并发。
    """
    chunk_id = state["chunk_id"]

    # 1. 幂等检查
    existing = await idempotency_store.get(chunk_id)
    if existing:
        return {"result": existing}

    # 2. 背压检查
    await backpressure_controller.wait_if_throttled()

    # 3. 调用后端批量 API
    try:
        result = await fiber_http_client.post(
            "/api/v1/fibers/performance/batch",
            json={"fiber_ids": state["fiber_ids"], "chunk_id": chunk_id},
            timeout=5.0
        )
        # 4. 记录幂等标记
        await idempotency_store.save(chunk_id, result, ttl=300)
        return {"result": json.loads(result)}
    except Exception as e:
        return {"error": str(e)}


def batch_aggregator_node(state: FiberAgentState) -> dict:
    """
    聚合节点：合并所有 Chunk 结果（reducer 已自动合并 batch_results）。
    执行分层聚合，仅将摘要传给 LLM。
    """
    all_results = state["batch_results"]  # 由 operator.add reducer 自动合并

    # 第一层：程序化统计（零 token）
    total = sum(r.get("count", 0) for r in all_results)
    normal = sum(r.get("normal_count", 0) for r in all_results)
    abnormal = total - normal
    colors = aggregate_colors(all_results)
    spanloss_stats = compute_spanloss_stats(all_results)

    # 第二层：异常筛选（零 token）
    red_fibers = extract_red_fibers(all_results)
    top_anomalies = extract_top_anomalies(all_results, top_n=10)

    # 第三层：组装摘要（≈ 3500 tokens → 传给 analysis_expert）
    summary = {
        "total": total,
        "normal": normal,
        "abnormal": abnormal,
        "color_distribution": colors,
        "spanloss_stats": spanloss_stats,
        "red_fibers": red_fibers,
        "top_anomalies": top_anomalies,
    }

    return {
        "fiber_data": summary,
        "batch_progress": {"completed": len(all_results), "total": len(all_results)},
    }
```

### 7.2 四要素映射

| 要素          | LangGraph 实现                           | 核心参数                    |
| ------------- | ---------------------------------------- | --------------------------- |
| **分块**      | `batch_dispatcher_node` 中 chunk_size=50 | MAX_CHUNKS=4, MAX_TOTAL=200 |
| **游标/断点** | LangGraph **Checkpointer** (SqliteSaver) | 自动持久化每个 Send 的状态  |
| **背压**      | `backpressure_controller` 在 worker 内   | 错误率>10%→延迟1000ms       |
| **幂等**      | `idempotency_store` (SQLite)             | chunk_id 去重, TTL=300s     |

### 7.3 Checkpointer 断点续传（LangGraph 原生能力）

```python
# 批量任务中断后恢复（LangGraph 原生支持）
config = {"configurable": {"thread_id": "batch_task_001"}}

# 首次执行（可能中断）
result = await graph.ainvoke(initial_state, config)

# 中断后恢复（从最近 Checkpoint 继续）
# LangGraph 自动跳过已完成的 Chunk（幂等 + Checkpoint）
result = await graph.ainvoke(None, config)  # 传 None 表示恢复
```

> **对比原始方案**：原始方案需手动实现游标表 + 断点逻辑；LangGraph Checkpointer **原生提供**状态快照与恢复，零额外代码。

------

## 第八部分：Callbacks 管道设计（横切关注点）

### 8.1 LangChain Callbacks 机制

```python
from langchain_core.callbacks import BaseCallbackHandler

class AuthCallback(BaseCallbackHandler):
    """认证回调：验证用户身份"""
    def on_chain_start(self, serialized, inputs, **kwargs):
        token = inputs.get("config", {}).get("metadata", {}).get("auth_token")
        if not validate_token(token):
            raise AuthenticationError("无效凭证")

class RateLimitCallback(BaseCallbackHandler):
    """限流回调：令牌桶 10 req/min"""
    def __init__(self):
        self.bucket = TokenBucket(rate=10, burst=20)

    def on_llm_start(self, serialized, prompts, **kwargs):
        if not self.bucket.acquire():
            raise RateLimitError("请求过于频繁")

class TracingCallback(BaseCallbackHandler):
    """追踪回调：记录全链路 Span"""
    def on_chain_start(self, serialized, inputs, **kwargs):
        self.span = tracer.start_span(serialized.get("name", "unknown"))

    def on_chain_end(self, outputs, **kwargs):
        self.span.end()
```

### 8.2 回调注册

```python
# 全局回调（所有 LLM/Chain/Tool 调用均触发）
callbacks = [
    AuthCallback(),
    RateLimitCallback(),
    TracingCallback(),
]

# 方式 1：全局配置
config = {"callbacks": callbacks}

# 方式 2：LangServe 应用级
app = LangServe(graph, config={"callbacks": callbacks})
```

### 8.3 RAG 前置注入（Callback 实现）

```python
class RAGInjectionCallback(BaseCallbackHandler):
    """RAG 前置注入：在 LLM 调用前自动注入知识上下文"""

    def __init__(self, retriever):
        self.retriever = retriever

    async def on_llm_start(self, serialized, prompts, **kwargs):
        # 仅对分析/报告类节点生效
        node_name = kwargs.get("tags", [""])[0]
        if node_name not in ["analysis_expert", "report_generator"]:
            return

        # 检索 + 注入
        query = prompts[0] if prompts else ""
        docs = await self.retriever.ainvoke(query)
        context = "\n".join([d.page_content for d in docs[:3]])

        # 修改 prompts（注入知识）
        prompts[0] += f"\n\n## 参考知识\n{context}"
```

------

## 第九部分：记忆系统设计

### 9.1 双层记忆（LangGraph Checkpointer + 自定义 Store）

| 层级     | LangGraph 实现                                   | 容量              | 生命周期     |
| -------- | ------------------------------------------------ | ----------------- | ------------ |
| 短期记忆 | **Checkpointer** (SqliteSaver) 自动保存 messages | 最近 30 条        | 会话结束清除 |
| 长期记忆 | 自定义 **MemoryStore** (SQLite)                  | 指标快照 <200B/条 | 90 天        |

### 9.2 长期记忆 Tool

```python
@tool
async def memory_save(fiber_id: str, spanloss: float, color: str, summary: str) -> str:
    """保存光纤指标快照到长期记忆（仅颜色变化时写入）"""
    existing = await memory_store.get_latest(fiber_id)
    if existing and existing["color"] == color:
        return "颜色未变化，跳过写入"
    await memory_store.save(fiber_id, spanloss, color, summary)
    return f"已保存 {fiber_id} 快照: {color}, {spanloss}dB"

@tool
async def memory_query(fiber_id: str, days: int = 30) -> str:
    """查询光纤历史指标快照"""
    records = await memory_store.query(fiber_id, days=days)
    return json.dumps(records, ensure_ascii=False)
```

### 9.3 Checkpointer 配置

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# 异步版本（生产推荐）
checkpointer = AsyncSqliteSaver.from_conn_string("data/checkpoints.db")

# 编译时注入
graph = main_graph.compile(checkpointer=checkpointer)

# 调用时指定 thread_id（每个会话独立状态）
config = {"configurable": {"thread_id": "user_session_001"}}
result = await graph.ainvoke({"messages": [HumanMessage(content="...")]}, config)
```

------

## 第十部分：RAG 知识检索设计

### 10.1 LangChain Retriever 构建

```python
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

# Embedding
embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-zh-v1.5")

# 向量检索
vectorstore = Chroma(
    collection_name="fiber_knowledge",
    embedding_function=embeddings,
    persist_directory="data/chromadb",
)
vector_retriever = vectorstore.as_retriever(
    search_kwargs={"k": 5, "score_threshold": 0.6}
)

# BM25 检索
bm25_retriever = BM25Retriever.from_documents(all_documents, k=5)

# 混合检索 (Vector 0.6 + BM25 0.4)
hybrid_retriever = EnsembleRetriever(
    retrievers=[vector_retriever, bm25_retriever],
    weights=[0.6, 0.4],
)

# Reranker（可选）
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain.retrievers.document_compressors import CrossEncoderReranker

reranker = CrossEncoderReranker(
    model=HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-v2-m3"),
    top_n=3,
)
final_retriever = ContextualCompressionRetriever(
    base_compressor=reranker,
    base_retriever=hybrid_retriever,
)
```

### 10.2 RAG Tool

```python
@tool
async def rag_query(query: str, category: str = "all") -> str:
    """检索光纤维护知识库，返回最相关的 3 条知识片段"""
    docs = await final_retriever.ainvoke(query)
    results = []
    for doc in docs[:3]:
        results.append({
            "content": doc.page_content[:500],
            "source": doc.metadata.get("source", "unknown"),
            "category": doc.metadata.get("category", "general"),
            "score": doc.metadata.get("relevance_score", 0),
        })
    return json.dumps(results, ensure_ascii=False)
```

### 10.3 知识库分类（6 类 16 篇）

| #    | Collection         | 内容                         | 文档数 |
| ---- | ------------------ | ---------------------------- | ------ |
| 1    | device_manual      | 有源盘/无源盘规格、端口约束  | 3      |
| 2    | maintenance_guide  | 巡检规范、抢修流程、安全规范 | 3      |
| 3    | alarm_guide        | 告警级别、处理流程、升级规则 | 3      |
| 4    | fault_cases        | 典型故障案例                 | 3      |
| 5    | threshold_standard | 衰耗阈值表、光功率范围       | 2      |
| 6    | ne_config          | 组网规则、配置约束           | 2      |

------

## 第十一部分：容错与降级设计（Conditional Edge）

### 11.1 四级降级（LangGraph 条件边实现）

```python
def check_degradation(state: FiberAgentState) -> str:
    """降级检查：条件边路由"""
    level = state.get("degradation_level", "L1")

    if level == "L1":
        return "normal"
    elif level == "L2":
        return "normal"  # 模型降级但仍在运行
    elif level == "L3":
        return "normal"  # 规则兜底，直接输出
    elif level == "L4":
        return "normal"  # 纯知识模式
    return "normal"


# LLM Fallback Chain（LangChain 原生）
from langchain_ollama import ChatOllama

llm_primary = ChatOllama(model="qwen2.5:7b", temperature=0.1)
llm_fallback = ChatOllama(model="qwen2.5:3b", temperature=0.1)
llm_fast = ChatOllama(model="qwen2.5:1.5b", temperature=0.1)

# LangChain with_fallbacks（原生降级链）
llm_with_fallback = llm_primary.with_fallbacks(
    [llm_fallback, llm_fast],
    exceptions_to_handle=(httpx.TimeoutException, httpx.ConnectError),
)
```

### 11.2 L3 规则兜底节点

```python
async def degradation_handler_node(state: FiberAgentState) -> dict:
    """降级处理节点"""
    level = state.get("degradation_level", "L1")

    if level == "L3":
        # 固定模板输出（白名单场景）
        intent = state["intent"].intent
        template = L3_TEMPLATES.get(intent)
        if template:
            report = template.format(**state["fiber_data"])
            return {"final_report": report}
        else:
            return {"final_report": "当前系统降级中，暂不支持该查询，请稍后重试。"}

    if level == "L4":
        # 纯知识模式：仅 RAG
        docs = await final_retriever.ainvoke(state["messages"][-1].content)
        answer = "\n".join([d.page_content for d in docs[:3]])
        return {"final_report": f"[离线模式] 基于知识库回答：\n{answer}"}

    return {}
```

### 11.3 降级链总览

```
L1 正常模式（qwen2.5:7b 可用）
    │ 主模型连续 3 次超时/5xx
    ▼
L2 模型降级: with_fallbacks([7b → 3b → 1.5b])  ← LangChain 原生
    │ 所有模型均不可用
    ▼
L3 规则兜底: L3_TEMPLATES 固定模板  ← Conditional Edge 路由
    │ 后端 API 也熔断
    ▼
L4 纯知识模式: 仅 RAG Retriever  ← Conditional Edge 路由
```

------

## 第十二部分：上下文窗口预算管理

### 12.1 预算分配（总计 8192 tokens）

| 区域          | 预算     | LangGraph 实现                |
| ------------- | -------- | ----------------------------- |
| System Prompt | 500      | 子图 prompt 固定部分          |
| 用户指令      | 300      | messages[-1]                  |
| 输出格式约束  | 500      | with_structured_output schema |
| **当前数据**  | **3000** | State.fiber_data（聚合压缩）  |
| **RAG 知识**  | **1000** | RAGInjectionCallback 截断     |
| **历史记忆**  | **500**  | memory_query 返回截断         |
| 安全余量      | 392      | —                             |
| **输出预留**  | **2000** | 永不让渡                      |

### 12.2 超限降级（State 内实现）

```python
def compress_context(state: FiberAgentState) -> FiberAgentState:
    """上下文压缩：按优先级裁剪"""
    total_tokens = estimate_tokens(state)
    budget = 8192 - 2000  # 输出预留

    if total_tokens <= budget:
        return state

    # P3: 压缩记忆 (3→1→0)
    state["memory_context"] = state["memory_context"][:1]

    # P2: 压缩 RAG (3→2→1→0)
    state["rag_context"] = state["rag_context"][:2]

    # P1: 压缩数据 (全量→Top10→Top5)
    if "top_anomalies" in state.get("fiber_data", {}):
        state["fiber_data"]["top_anomalies"] = state["fiber_data"]["top_anomalies"][:5]

    return state
```

------

## 第十三部分：可观测性设计

### 13.1 LangSmith / LangFuse 集成

```python
import os

# 方式 1：LangSmith（LangChain 官方）
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "ls__xxx"
os.environ["LANGCHAIN_PROJECT"] = "fiber-maintenance-agent"

# 方式 2：LangFuse（开源自部署）
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-xxx"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-xxx"
os.environ["LANGFUSE_HOST"] = "http://langfuse:3000"
```

### 13.2 自动追踪能力（零代码）

| 追踪项        | LangSmith/LangFuse 自动记录        |
| ------------- | ---------------------------------- |
| 图执行路径    | 每个 Node 的进入/退出/耗时         |
| LLM 调用      | Prompt/Completion/Tokens/温度/模型 |
| Tool 调用     | 入参/出参/耗时/错误                |
| Subgraph 嵌套 | 父子图关联                         |
| Send 并发     | 每个 Chunk 的独立 Trace            |
| Checkpoint    | 状态快照时间线                     |
| 总耗时        | 端到端延迟                         |
| Token 消耗    | 按节点/按模型统计                  |

### 13.3 自定义 Metrics（Prometheus）

```python
from prometheus_client import Counter, Histogram, Gauge

# 自定义指标
llm_call_total = Counter("fiber_llm_calls_total", "LLM 调用总数", ["model", "node"])
llm_latency = Histogram("fiber_llm_latency_seconds", "LLM 延迟", ["model"])
tool_call_total = Counter("fiber_tool_calls_total", "Tool 调用总数", ["tool_name"])
degradation_level = Gauge("fiber_degradation_level", "当前降级级别")
batch_progress = Gauge("fiber_batch_progress", "批量处理进度")
circuit_state = Gauge("fiber_circuit_breaker_state", "熔断器状态")
```

### 13.4 核心告警规则

| 告警           | 条件                   | 级别 |
| -------------- | ---------------------- | ---- |
| LLM 不可用     | 所有模型连续 3 次失败  | P0   |
| 降级至 L3      | degradation_level = L3 | P1   |
| 后端熔断       | circuit_breaker = OPEN | P1   |
| 延迟劣化       | P95 > 30s 持续 5min    | P2   |
| Token 成本异常 | 日累计 > 500K          | P2   |

------

## 第十四部分：Prompt 版本管理

### 14.1 目录结构

```
prompts/
├── VERSION                         # 当前全局版本号
├── CHANGELOG.md
├── lead_agent/
│   ├── intent_classifier.md        # 意图识别 Prompt
│   ├── task_decomposer.md          # 任务分解 Prompt
│   └── result_aggregator.md        # 结果聚合 Prompt
├── data_collector/
│   └── system.md                   # 数据收集 System Prompt
├── analysis_expert/
│   ├── system.md
│   └── few_shots/                  # Few-shot 示例
│       ├── spanloss_analysis.json
│       └── color_diagnosis.json
├── report_generator/
│   ├── system.md
│   └── templates/                  # 报告模板
│       ├── daily_report.md
│       └── fault_report.md
├── knowledge_assistant/
│   └── system.md
└── tests/
    ├── test_cases.yaml             # 回归测试用例
    └── run_regression.py           # 自动化回归
```

### 14.2 版本规范

- **major**: 角色定义/核心约束变更
- **minor**: 判定标准/输出格式调整
- **patch**: 措辞优化/typo 修复
- 变更必须走 PR + 回归测试 + 2 人 review
- LangSmith Prompt Hub 在线管理（可选）

------

## 第十五部分：导出与报告引擎

| 格式     | 实现库                 | LangChain Tool      |
| -------- | ---------------------- | ------------------- |
| PDF      | reportlab + matplotlib | `export_pdf`        |
| Excel    | openpyxl               | `export_excel`      |
| CSV      | csv 模块               | `export_csv`        |
| Markdown | 原生                   | 直接输出到 messages |

```python
@tool
async def export_pdf(title: str, content: str, charts: list[dict] = []) -> str:
    """将分析报告导出为 PDF 文件"""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph
    import matplotlib.pyplot as plt

    output_path = f"/tmp/fiber_reports/{uuid4().hex}.pdf"
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    # ... 生成 PDF
    return f"PDF 已导出: {output_path}"
```

------

## 第十六部分：完整部署方案

### 16.1 服务编排（Docker Compose，9 个容器）

| 服务              | 镜像/构建                  | 端口        | 职责                      |
| ----------------- | -------------------------- | ----------- | ------------------------- |
| ollama            | ollama/ollama:latest       | :11434      | LLM 推理 (qwen2.5)        |
| chromadb          | chromadb/chroma:latest     | :8100       | RAG 向量数据库            |
| fiber-backend     | ./fiber-backend            | :8080/:8081 | C++ 后端 REST+WS          |
| **langgraph-app** | ./langgraph-app            | **:8000**   | **LangGraph + LangServe** |
| langgraph-studio  | langchain/langgraph-studio | :8123       | 图可视化调试（开发）      |
| frontend          | ./frontend                 | :5173       | Vue3 统计面板             |
| langfuse          | langfuse/langfuse          | :3000       | 可观测平台                |
| prometheus        | prom/prometheus            | :9090       | 指标采集                  |
| grafana           | grafana/grafana            | :3001       | 监控看板                  |

### 16.2 LangServe 部署（LangGraph 应用暴露为 API）

```python
# server.py
from langserve import add_routes
from fastapi import FastAPI
from graph import build_main_graph

app = FastAPI(title="Fiber Maintenance Agent", version="5.0.0")
graph = build_main_graph()

# LangServe：自动暴露 /invoke, /stream, /batch 端点
add_routes(
    app,
    graph,
    path="/fiber-agent",
    # 启用流式输出
    enable_feedback_endpoint=True,
    enable_public_trace_link_endpoint=True,
)

# 自定义端点：批量任务进度查询
@app.get("/api/batch/{thread_id}/progress")
async def get_batch_progress(thread_id: str):
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return state.values.get("batch_progress", {})
```

### 16.3 启动顺序

```
ollama → chromadb → fiber-backend → langfuse → langgraph-app → frontend → prometheus + grafana
```

### 16.4 环境要求

| 组件   | 要求                       |
| ------ | -------------------------- |
| CPU    | ≥ 8 核                     |
| 内存   | ≥ 32GB（推荐 64GB）        |
| 磁盘   | ≥ 500GB SSD                |
| GPU    | 可选（NVIDIA ≥ 24GB VRAM） |
| Python | ≥ 3.11                     |
| Docker | ≥ 24.0 + Compose ≥ 2.20    |

------

## 第十七部分：项目目录结构（最终版）

```
fiber-maintenance-agent/
├── src/
│   ├── graph/                          # ★ LangGraph 图定义
│   │   ├── __init__.py
│   │   ├── main_graph.py               # 主编排图 (StateGraph)
│   │   ├── state.py                    # State 定义 (TypedDict)
│   │   ├── routing.py                  # 条件边路由函数
│   │   └── subgraphs/                  # ★ 4 个 Sub-Agent 子图
│   │       ├── data_collector.py
│   │       ├── analysis_expert.py
│   │       ├── report_generator.py
│   │       ├── knowledge_assistant.py
│   │       └── batch_processor.py      # Send 并发子图
│   ├── nodes/                          # ★ 图节点函数
│   │   ├── intent_classifier.py
│   │   ├── task_decomposer.py
│   │   ├── batch_dispatcher.py         # Send 派发
│   │   ├── batch_worker.py             # Send 执行
│   │   ├── batch_aggregator.py         # 聚合
│   │   ├── result_aggregator.py
│   │   └── degradation_handler.py
│   ├── tools/                          # ★ 18 个 LangChain Tools
│   │   ├── __init__.py
│   │   ├── topology_tools.py (4)
│   │   ├── performance_tools.py (2)
│   │   ├── alarm_tools.py (2)
│   │   ├── colored_tools.py (2)
│   │   ├── stats_tools.py (2)
│   │   ├── batch_tools.py (4)
│   │   ├── rag_tools.py (2)
│   │   ├── export_tools.py (3)
│   │   ├── memory_tools.py (2)
│   │   └── _http_client.py            # 熔断/重试/背压
│   ├── callbacks/                      # ★ LangChain Callbacks
│   │   ├── auth.py
│   │   ├── rate_limit.py
│   │   ├── rag_injection.py
│   │   └── tracing.py
│   ├── memory/                         # 记忆系统
│   │   ├── store.py                    # SQLite 长期记忆
│   │   └── schemas.py
│   ├── rag/                            # RAG 检索
│   │   ├── retriever.py               # 混合检索 + Reranker
│   │   ├── embeddings.py
│   │   └── ingest.py                  # 知识库导入
│   ├── llm/                            # LLM 配置
│   │   ├── provider.py                # ChatOllama + Fallback
│   │   └── prompts.py                 # Prompt 加载
│   ├── export/                         # 导出引擎
│   │   ├── pdf.py
│   │   ├── excel.py
│   │   └── csv.py
│   └── server.py                       # ★ LangServe 入口
├── prompts/                            # Prompt 版本管理
├── knowledge_base/                     # RAG 知识库（6类）
├── frontend/                           # Vue3 统计面板
├── fiber-backend/                      # C++ 后端
├── tests/                              # 测试
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── monitoring/                         # Prometheus + Grafana
├── docs/                               # 文档
├── data/                               # 运行时数据
│   ├── checkpoints.db                  # LangGraph Checkpointer
│   ├── memory.db                       # 长期记忆
│   └── chromadb/                       # 向量数据
├── pyproject.toml                      # 依赖管理
├── docker-compose.yaml                 # ★ 部署编排
├── Dockerfile
├── .env.example
├── langgraph.json                      # ★ LangGraph Studio 配置
├── .gitlab-ci.yml                      # CI/CD
└── Makefile
```

------

## 第十八部分：依赖清单（pyproject.toml）

```toml
[project]
name = "fiber-maintenance-agent"
version = "5.0.0"
requires-python = ">=3.11"
dependencies = [
    # LangChain 核心
    "langchain>=0.3.27",
    "langchain-core>=0.3.60",
    "langchain-community>=0.3.20",
    "langchain-ollama>=0.3.0",
    "langchain-chroma>=0.2.0",
    # LangGraph 核心
    "langgraph>=1.0.8",
    "langgraph-checkpoint-sqlite>=2.0.0",
    # LangServe（API 暴露）
    "langserve>=0.3.0",
    # Web 框架
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    # HTTP 客户端
    "httpx>=0.28.0",
    # RAG
    "chromadb>=0.6.0",
    "sentence-transformers>=3.4.0",
    # 导出
    "reportlab>=4.3.0",
    "openpyxl>=3.1.0",
    "matplotlib>=3.10.0",
    # 可观测
    "langsmith>=0.3.0",
    "prometheus-client>=0.21.0",
    # 数据
    "pydantic>=2.10.0",
    "aiosqlite>=0.20.0",
]
```

------

## 第十九部分：LangGraph Studio 配置（开发调试）

```json
// langgraph.json
{
  "dependencies": ["."],
  "graphs": {
    "fiber_agent": "./src/graph/main_graph.py:build_main_graph"
  },
  "env": ".env",
  "python_version": "3.11",
  "dockerfile_lines": []
}
```

> LangGraph Studio 提供**图结构可视化、状态时间旅行、节点级断点调试、Send 并发可视化**，是开发阶段的核心调试工具。

------

## 第二十部分：开发路线图（4 周）

| 周次 | 工作                                                  | 产出            | 验收标准                    |
| ---- | ----------------------------------------------------- | --------------- | --------------------------- |
| W11  | LangGraph 环境搭建 + OLLAMA + 主图骨架 + Checkpointer | 运行环境        | 图可编译，Checkpoint 可写入 |
| W12  | 18 Tools + HTTP Client(熔断) + 4 子图 + Callbacks     | 工具层+子图完整 | 所有 Tool 可调用后端        |
| W13  | Send 批量 + RAG + 记忆 + 降级链 + 结构化输出          | 端到端对话      | 5 类场景 + 批量可用         |
| W14  | LangServe + Vue3 面板 + 导出 + LangFuse + 联调        | 全功能          | ETCLOVG 验收通过            |

------

## 第二十一部分：验收标准（ETCLOVG）

| 维度              | 验收项   | 通过标准                                      |
| ----------------- | -------- | --------------------------------------------- |
| **E**nvironment   | 环境部署 | Docker Compose 一键启动，所有服务健康         |
| **T**ools         | 工具调用 | 18 个 @tool 全部可正确调用后端 API            |
| **C**onversation  | 对话能力 | 单条/批量/趋势/巡检/知识问答 5 类场景通过     |
| **L**ogic         | 业务逻辑 | 颜色/衰耗结果与后端一致，无误判               |
| **O**utput        | 输出质量 | 报告结构完整，建议合理，引用准确              |
| **V**isualization | 可视化   | 统计面板实时刷新 + LangGraph Studio 图可视化  |
| **G**raceful      | 容错降级 | 后端断开→L4，模型超时→with_fallbacks 自动降级 |

------

## 第二十二部分：与原始方案的关键差异总结

| 维度       | 原始方案 (v3.2.1/v4.0) | LangChain + LangGraph 版                     |
| ---------- | ---------------------- | -------------------------------------------- |
| 编排模型   | 自研调度循环           | **StateGraph 有向状态图**                    |
| Agent 实现 | 自研类                 | **Subgraph（子图）**                         |
| 批量并发   | 自研 asyncio 分块      | **Send 机制（原生 Map-Reduce）**             |
| 断点续传   | 自研游标表             | **Checkpointer（原生状态快照）**             |
| 工具定义   | 自定义类               | **@tool 装饰器 + Pydantic Schema**           |
| 工具执行   | 手动调用               | **ToolNode（内置）**                         |
| 降级链     | 自研 if/elif           | **with_fallbacks + Conditional Edge**        |
| 结构化输出 | 手动 JSON 解析         | **with_structured_output（Pydantic）**       |
| 横切关注点 | 自研管道               | **Callbacks（生命周期钩子）**                |
| 可观测性   | 手动埋点               | **LangSmith/LangFuse（零代码自动追踪）**     |
| 图调试     | 无                     | **LangGraph Studio（可视化+时间旅行）**      |
| API 暴露   | 自研 FastAPI           | **LangServe（自动 /invoke /stream /batch）** |
| 人工介入   | 无                     | **interrupt()（原生支持）**                  |
| 状态管理   | 手动传递               | **TypedDict State + Reducer（自动合并）**    |

------

## 附录 A：关键设计决策追溯

| 决策       | 选择                              | 依据                                          |
| ---------- | --------------------------------- | --------------------------------------------- |
| 编排框架   | LangGraph StateGraph              | 有向图 + 条件边 + 循环，天然适配多 Agent 调度 |
| 批量并发   | Send 机制                         | LangGraph 原生 Map-Reduce，无需手动 asyncio   |
| 断点续传   | Checkpointer (SQLite)             | 框架原生，零额外代码                          |
| 降级实现   | with_fallbacks + Conditional Edge | LangChain 原生 + LangGraph 路由               |
| 可观测     | LangFuse（自部署）                | 开源、数据不出内网                            |
| 结构化输出 | with_structured_output            | 消除 JSON 解析失败风险                        |
| 子图隔离   | Subgraph                          | 工具权限天然隔离（P2 原则）                   |
| 横切关注点 | Callbacks                         | LangChain 标准机制，不侵入业务代码            |

------

## 附录 B：LangGraph 核心 API 速查

| API                                       | 用途         | 本系统使用       |
| ----------------------------------------- | ------------ | ---------------- |
| `StateGraph(State)`                       | 创建图       | 主图 + 4 子图    |
| `graph.add_node(name, fn)`                | 注册节点     | 11 个节点        |
| `graph.add_edge(a, b)`                    | 固定边       | 顺序流程         |
| `graph.add_conditional_edges(a, fn, map)` | 条件边       | 意图路由 + 降级  |
| `Send(node, state)`                       | 并发派发     | 批量分块         |
| `graph.compile(checkpointer=...)`         | 编译图       | SqliteSaver      |
| `graph.ainvoke(state, config)`            | 异步执行     | 主入口           |
| `graph.astream(state, config)`            | 流式输出     | LangServe        |
| `graph.aget_state(config)`                | 获取状态     | 进度查询         |
| `interrupt()`                             | 人工介入     | 批量确认（预留） |
| `Command(goto=node)`                      | 动态路由     | 降级跳转         |
| `create_react_agent(model, tools)`        | ReAct Agent  | data_collector   |
| `ToolNode(tools)`                         | 工具执行节点 | 子图内           |
| `with_structured_output(Schema)`          | 结构化输出   | 意图/分析        |
| `with_fallbacks([...])`                   | 模型降级链   | L2 降级          |

------

*— 文档结束 —*